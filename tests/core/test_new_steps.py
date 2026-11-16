from pathlib import Path

import pytest

from ifcat.grid import find_column
from ifcat.result import BlockedError
from ifcat.scenario import CHECKPOINT_STEPS, STEP_SPECS, parse_scenario


class _Col:
    def __init__(self, header, key):
        self.header, self.key = header, key


class _Grid:
    key = "G"

    def __init__(self, cols):
        self.columns = cols


def test_grid_column_matches_name_without_required_star():
    g = _Grid([_Col("*跃息年利率", "Column3"), _Col("周期", "Column1")])
    assert find_column(g, "跃息年利率").key == "Column3"
    assert find_column(g, "*跃息年利率").key == "Column3"
    with pytest.raises(BlockedError):
        find_column(g, "不存在")


def test_new_step_kinds_are_registered_and_checkpoints():
    for name in ("edit", "open_todo", "submit_with_warning", "approve_blocked", "expect_visible", "reject"):
        assert name in STEP_SPECS
    assert {"submit_with_warning", "approve_blocked", "expect_visible"} <= CHECKPOINT_STEPS


def _scenario():
    return parse_scenario({
        "id": "T-1", "title": "余额不足", "module": "DP", "feature": "企业定存存入", "kind": "核心异常",
        "roles": {"maker": "经办", "checker": "审核"},
        "steps": [
            {"id": "s1", "as": "maker", "do": "submit_with_warning", "说明": "提交并提醒",
             "args": {"form": "F", "warning": "余额不足", "then": "继续处理"}},
            {"id": "s2", "as": "checker", "do": "approve_blocked", "说明": "同意被拦截",
             "args": {"bill": "B1", "message": "当前可用余额不足"}},
            {"id": "s3", "as": "maker", "do": "expect_visible", "说明": "不显示到期日期",
             "args": {"form": "F", "label": "到期日期", "visible": False}},
        ],
    })


def test_review_page_shows_new_checkpoints_in_business_words():
    sc = _scenario()
    from ifcat.reviewpage import _detail
    texts = [_detail(s, sc) for s in sc.steps]
    assert "余额不足" in texts[0] and "继续处理" in texts[0]
    assert "当前可用余额不足" in texts[1]
    assert "不显示" in texts[2]
