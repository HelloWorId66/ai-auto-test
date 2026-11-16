"""把本地扩展适配器打包成合入核心的提案（供维护者审核）。

用法：python tools/propose.py <工作区>/extensions/某适配器.py "为什么需要、在哪个真实页面验证过"
提案目录生成在该工作区的 proposals/ 下，交给维护者审核；本脚本不改动框架核心。
"""
import shutil
import sys
from datetime import date
from pathlib import Path

if len(sys.argv) < 3:
    sys.exit(__doc__)
src, why = Path(sys.argv[1]), sys.argv[2]
if not src.is_file():
    sys.exit(f"找不到 {src}")
out = src.resolve().parent.parent / "proposals" / f"{date.today():%Y%m%d}-{src.stem}"
out.mkdir(parents=True, exist_ok=True)
shutil.copy(src, out / src.name)
(out / "PROPOSAL.md").write_text(
    f"# 提案：{src.stem}\n\n## 原因与验证\n{why}\n\n## 维护者检查清单\n"
    "- [ ] 选择器有真实页面证据\n- [ ] 带自测样本\n- [ ] 不与核心适配器冲突\n- [ ] 通过后跑 tools/release_manifest.py 并升版本\n",
    encoding="utf-8")
print(out)
