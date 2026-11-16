"""维护者发版时运行：重新生成核心库 MANIFEST.json。普通使用者和智能体不要运行。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from ifcat import guard  # noqa: E402

print(guard.write_manifest())
