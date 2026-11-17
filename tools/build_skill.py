"""维护者发版时运行：把规程、参考文档、引擎和启动脚本打成一个可以直接分发的技能目录。

用法：
  python tools/build_skill.py                      生成 dist/ifc-autotest/
  python tools/build_skill.py --out <目录>          生成到 <目录>/ifc-autotest/
  python tools/build_skill.py --install <技能目录>  生成后再复制到 <技能目录>/ifc-autotest/（如 ~/.claude/skills）

使用者只需要这个技能目录，不需要框架仓库。打包前会做核心库完整性校验，没有通过就不打包。
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from ifcat import CORE_VERSION, guard  # noqa: E402

NAME = "ifc-autotest"
SKILL_SRC = ROOT / "skills" / NAME
ENGINE_TOOLS = ("db_mcp.py", "kb_query.py", "discover_bill.py", "propose.py")
_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def build(out_root: Path) -> Path:
    guard.verify_integrity()
    dst = out_root / NAME
    if dst.exists():
        _remove_previous(dst)
    shutil.copytree(SKILL_SRC, dst, ignore=_SKIP)
    engine = dst / "engine"
    shutil.copytree(ROOT / "core", engine / "core", ignore=_SKIP)
    shutil.copytree(ROOT / "templates", engine / "templates", ignore=_SKIP)
    (engine / "ui").mkdir()
    shutil.copy(ROOT / "ui" / "server.py", engine / "ui" / "server.py")
    (engine / "tools").mkdir()
    for name in ENGINE_TOOLS:
        shutil.copy(ROOT / "tools" / name, engine / "tools" / name)
    shutil.copy(ROOT / "ifc.py", engine / "ifc.py")
    shutil.copy(ROOT / "requirements.lock", engine / "requirements.lock")
    (dst / "VERSION").write_text(CORE_VERSION + "\n", encoding="utf-8")
    return dst


def _remove_previous(dst: Path) -> None:
    """只删除确实是本技能旧发布件的目录，避免误删别的东西。"""
    if not (dst / "SKILL.md").is_file() or not (dst / "VERSION").is_file():
        raise SystemExit(f"{dst} 已存在但不是 {NAME} 的发布件，请手工确认后删除")
    shutil.rmtree(dst)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="打包 ifc-autotest 技能")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--install", help="再复制到这个技能目录下，如 ~/.claude/skills")
    a = ap.parse_args(argv)
    try:
        dst = build(Path(a.out).expanduser().resolve())
    except guard.IntegrityError as exc:
        print(f"核心库完整性校验没有通过，不能打包：{exc}", file=sys.stderr)
        return 2
    print(f"已生成 {dst}（版本 {CORE_VERSION}）")
    if a.install:
        target = Path(a.install).expanduser().resolve() / NAME
        if target.exists():
            _remove_previous(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dst, target)
        print(f"已安装到 {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
