"""本地运行页面：选环境、选范围（全部/模块/单个场景）、启动、看报告和历史。只监听本机 127.0.0.1。

用法：python ui/server.py --workspace <工作区目录> [--port 8765]
只运行已审核的场景（未审核的会在报告里列为「未运行」）；页面显示每个场景的审核状态，并可打开审核页和历史报告。
页面不读取、不显示任何口令；口令来自启动本页面的终端里已设置的环境变量。
"""
import argparse
import html
import mimetypes
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from ifcat.batch import load_candidates  # noqa: E402
from ifcat.reviewpage import review_page_name  # noqa: E402
from ifcat.workspace import load_workspace  # noqa: E402

e = html.escape
WS = None
PROC = {"p": None, "scope": ""}


def candidates():
    return load_candidates(WS, WS.scenario_files())


def scenarios():
    """(相对路径, 审核状态或错误文字)。"""
    out = []
    for c in candidates():
        rel = str(c.path.relative_to(WS.scenarios_dir))
        out.append((rel, c.state if c.state else f"无法解析：{c.error}"))
    return out


def running():
    p = PROC["p"]
    return p is not None and p.poll() is None


def page():
    sc = candidates()
    modules = sorted({c.scenario.module for c in sc if c.scenario})
    approved = [str(c.path.relative_to(WS.scenarios_dir)) for c in sc if c.state and c.state.approved]
    opt = lambda xs: "".join(f"<option>{e(x)}</option>" for x in xs)
    scope = "<option value=all>全部场景</option>" + "".join(f"<option value='module:{e(m)}'>模块 {e(m)}</option>" for m in modules) \
        + "".join(f"<option value='scenario:{e(n)}'>{e(n)}</option>" for n in approved)
    rows = ""
    for c in sc:
        rel = str(c.path.relative_to(WS.scenarios_dir))
        state = c.state.describe() if c.state else f"无法解析：{c.error}"
        review = ""
        if c.scenario and (WS.reviews_dir / review_page_name(c.scenario)).is_file():
            review = f"<a href='/files/reviews/{quote(review_page_name(c.scenario))}'>审核页</a>"
        rows += (f"<tr><td>{e(c.scenario.module if c.scenario else '')}</td><td>{e(rel)}</td>"
                 f"<td>{e(state)}</td><td>{review}</td></tr>")
    banner = ""
    if running():
        banner = f"<p><b>正在运行：{e(PROC['scope'])}</b>。每跑完一个场景报告就会更新，刷新页面或打开报告查看。</p>"
    elif PROC["p"] is not None:
        banner = f"<p>上一次运行已结束（退出码 {PROC['p'].returncode}）：{e(PROC['scope'])}</p>"
    return f"""<meta charset=utf-8><title>IFC 自动化测试</title>
<style>body{{font:14px -apple-system,'PingFang SC',sans-serif;margin:24px}}td,th{{padding:4px 10px;text-align:left}}</style>
<h2>运行（工作区：{e(WS.project)}）</h2>{banner}<form method=post action=/run>
环境 <select name=env>{opt(WS.envs())}</select> 范围 <select name=scope>{scope}</select>
<button>启动</button></form>
<p>只运行已审核的场景，未审核的会在报告里列为「未运行」。<a href='/files/results/index.html'>查看全部历史报告</a></p>
<h2>场景</h2><table border=1 cellspacing=0><tr><th>模块</th><th>场景</th><th>审核状态</th><th></th></tr>{rows}</table>"""


def scope_args(scope):
    """校验页面传来的范围，只接受已知的值，返回命令行参数。"""
    if scope == "all":
        return ["--all"]
    kind, _, val = scope.partition(":")
    if kind == "module" and val in {c.scenario.module for c in candidates() if c.scenario}:
        return ["--module", val]
    if kind == "scenario" and val in [n for n, s in scenarios() if getattr(s, "approved", False)]:
        return [val]
    return None


class H(BaseHTTPRequestHandler):
    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self._send(page())
        if path.startswith("/files/"):
            base, _, rest = path[len("/files/"):].partition("/")
            root = {"results": WS.results_dir, "reviews": WS.reviews_dir}.get(base)
            if root is not None:
                target = (root / rest).resolve()
                if target.is_file() and root.resolve() in target.parents:
                    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                    if ctype.startswith("text/") or ctype == "application/json":
                        ctype += "; charset=utf-8"
                    return self._send(target.read_bytes(), ctype=ctype)
        self._send("not found", 404)

    def do_POST(self):
        if self.path != "/run":
            return self._send("not found", 404)
        q = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        env, scope = q.get("env", [""])[0], q.get("scope", [""])[0]
        args = scope_args(scope)
        if env not in WS.envs() or args is None:
            return self._send("无效选择，或场景未审核", 400)
        if running():
            return self._send("已有一次运行在进行中，请等它结束", 409)
        PROC["scope"] = f"{env} / {scope}"
        PROC["p"] = subprocess.Popen(
            [sys.executable, str(ROOT / "ifc.py"), "--workspace", str(WS.root), "run", *args, "--env", env],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    WS = load_workspace(args.workspace)
    print(f"http://127.0.0.1:{args.port}")
    HTTPServer(("127.0.0.1", args.port), H).serve_forever()
