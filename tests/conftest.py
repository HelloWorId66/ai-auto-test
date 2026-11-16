import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))


@pytest.fixture(autouse=True)
def _reset_workspace_extensions():
    """扩展动作和扩展方言是进程级的，测试之间不能互相带着走。"""
    yield
    from ifcat import actions, dbro

    actions.clear_extension_actions()
    dbro.clear_extension_dialects()
