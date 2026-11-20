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

def test_retake_registered_and_db_count_rendered_and_validated():
    assert STEP_SPECS["retake"] == ["bill"] and "retake" not in CHECKPOINT_STEPS
    sc = parse_scenario({
        "id": "T-2", "title": "取回", "module": "DP", "feature": "企业定存存入", "kind": "主流程",
        "roles": {"maker": "经办"}, "labels": {"change_log": "额度变动记录", "F_BDLX": "变动类型", "F_BDLX=1": "占用"},
        "steps": [
            {"id": "s1", "as": "maker", "do": "retake", "说明": "经办取回", "args": {"bill": "B1"}},
            {"id": "d1", "as": "maker", "do": "expect_db_record", "说明": "占用记录一条",
             "args": {"flow": "X", "key": "B1", "table": "change_log", "where": {"F_BDLX": "1"}, "count": 1,
                      "expect": {"F_JE": "100"}}},
            {"id": "d2", "as": "maker", "do": "expect_db_record", "说明": "还没有占用",
             "args": {"flow": "X", "key": "B1", "table": "change_log", "where": {"F_BDLX": "1"}, "count": 0}},
        ],
    })
    from ifcat.reviewpage import _detail
    from ifcat.scenario import action_text, validate_scenario
    assert action_text("retake") == "取回" and "B1" in _detail(sc.steps[0], sc)
    d1, d2 = _detail(sc.steps[1], sc), _detail(sc.steps[2], sc)
    assert "正好有 <b>1</b> 条" in d1 and "占用" in d1 and "每一条都应为" in d1
    assert "不应有「额度变动记录」" in d2 and "占用" in d2
    bad = parse_scenario({
        "id": "T-3", "title": "x", "module": "DP", "feature": "f", "kind": "主流程", "roles": {"maker": "经办"},
        "steps": [{"id": "d1", "as": "maker", "do": "expect_db_record", "说明": "x",
                   "args": {"flow": "X", "key": "B1", "table": "t", "count": -1, "where": ["F_A"]}}]})
    msgs = " ".join(str(i) for i in validate_scenario(bad, {}))
    assert "count" in msgs and "where" in msgs
