"""ifc-autotest 技能的命令入口。只用 Python 自带的库，任何 Python 3.10+ 都能直接运行。

  python <技能目录>/scripts/ifc.py <ifc 命令和参数>     运行引擎命令（doctor、list、validate、render、approve、run……）
  python <技能目录>/scripts/ifc.py setup [--force]       准备运行环境（第一次用任何命令时会自动做）
  python <技能目录>/scripts/ifc.py ui --workspace <目录>  本地运行页面
  python <技能目录>/scripts/ifc.py tool <工具名> <参数>   辅助工具：db_mcp、kb_query、discover_bill、propose
  python <技能目录>/scripts/ifc.py version               技能版本和运行环境位置

运行环境（Python 依赖和浏览器）装在本机用户目录 ~/.ifc-autotest 下，所有项目共用，不放在技能目录里。
可用环境变量：IFCAT_HOME 换一个存放位置；IFCAT_PYTHON 指定一个已装好依赖的 Python，跳过自动准备。
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
SKILL_DIR = Path(__file__).resolve().parents[1]
# 发布件里引擎在 <技能目录>/engine；在框架开发仓库里直接用仓库根目录
ENGINE = SKILL_DIR / "engine" if (SKILL_DIR / "engine").is_dir() else SKILL_DIR.parents[1]
LOCK = ENGINE / "requirements.lock"
TOOLS = ("db_mcp", "kb_query", "discover_bill", "propose")


def say(msg):
    print(msg, file=sys.stderr, flush=True)


def home():
    return Path(os.environ.get("IFCAT_HOME") or Path.home() / ".ifc-autotest").expanduser()


def env_dir():
    digest = hashlib.sha256(LOCK.read_bytes()).hexdigest()[:12]
    return home() / "envs" / f"py{sys.version_info.major}{sys.version_info.minor}-{digest}"


def env_python(env):
    return env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def version():
    f = SKILL_DIR / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.is_file() else "开发版"


def _step(title, cmd, log):
    say(f"  {title} ……")
    with log.open("a", encoding="utf-8") as out:
        out.write(f"\n$ {' '.join(str(c) for c in cmd)}\n")
        out.flush()
        code = subprocess.call(cmd, stdout=out, stderr=subprocess.STDOUT)
    if code != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        say("  失败。日志最后几行：\n    " + "\n    ".join(tail))
        say(f"  完整日志：{log}")
        say("  常见原因：没有连上网络或公司内网、pip 源不可用、磁盘空间不足。处理后重新执行同一条命令即可。")
        raise SystemExit(2)


def setup(force=False):
    """准备运行环境；已经准备好就直接返回它的 Python。"""
    override = os.environ.get("IFCAT_PYTHON")
    if override:
        return Path(override)
    if sys.version_info < MIN_PYTHON:
        say(f"需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高，当前是 {sys.version.split()[0]}。请安装新版 Python 后用它运行本命令。")
        raise SystemExit(2)
    if not LOCK.is_file():
        say(f"技能目录不完整，缺少 {LOCK}。请重新安装 ifc-autotest 技能。")
        raise SystemExit(2)
    env = env_dir()
    py = env_python(env)
    ready = env / "READY"
    if ready.is_file() and py.is_file() and not force:
        return py
    say(f"第一次使用（或依赖版本有更新），正在准备运行环境，需要几分钟，只做这一次。位置：{env}")
    if env.exists():
        shutil.rmtree(env)
    env.parent.mkdir(parents=True, exist_ok=True)
    log = home() / "setup.log"
    log.write_text("", encoding="utf-8")
    _step("创建独立的 Python 环境", [sys.executable, "-m", "venv", str(env)], log)
    _step("安装依赖", [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(LOCK)], log)
    _step("安装自动化浏览器", [str(py), "-m", "playwright", "install", "chromium"], log)
    ready.write_text(version(), encoding="utf-8")
    say("运行环境已准备好。")
    return py


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "version":
        env = env_dir() if LOCK.is_file() else None
        print(f"ifc-autotest {version()}")
        print(f"引擎：{ENGINE}")
        print(f"运行环境：{os.environ.get('IFCAT_PYTHON') or env}"
              f"（{'已准备好' if os.environ.get('IFCAT_PYTHON') or (env and (env / 'READY').is_file()) else '尚未准备，首次运行命令时自动准备'}）")
        return 0
    if cmd == "setup":
        setup(force="--force" in rest)
        return 0
    if cmd == "ui":
        target = [str(ENGINE / "ui" / "server.py"), *rest]
    elif cmd == "tool":
        if not rest or rest[0] not in TOOLS:
            say(f"用法：ifc.py tool <{'|'.join(TOOLS)}> <参数>")
            return 2
        target = [str(ENGINE / "tools" / f"{rest[0]}.py"), *rest[1:]]
    else:
        target = [str(ENGINE / "ifc.py"), *argv]
    py = setup()
    child_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.call([str(py), *target], env=child_env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
