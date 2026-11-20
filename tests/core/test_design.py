"""用例设计：写成 YAML，生成给业务人员确认的 HTML 页面；它不是场景，不被引擎执行。"""
from pathlib import Path

import pytest
import yaml

from ifcat.cli import main
from ifcat.design import DesignError, load_design, render_design_html
from ifcat.workspace import load_workspace

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "skills" / "ifc-autotest" / "references" / "用例设计模板.yaml"

DESIGN = {
    "module": "LM", "feature": "授信申请", "menu": "企业业务 > 授信申请",
    "rules": [{"id": "R1", "rule": "编号由系统生成", "source": "真实页面", "verified": "已核实"}],
    "cases": [{"title": "申请后办结", "kind": "主流程", "goal": "能走通",
               "data": {"申请人": "甲公司"},
               "steps": [{"who": "制单人", "do": "保存", "expect": "生成编号 <R1>"}]}],
    "questions": ["金额不一致时要不要拦？"],
}
SCENARIO = ("id: LM-演示\ntitle: 演示\nmodule: LM\ngoal: 演示\nroles: {maker: 制单员}\nsteps:\n"
            "  - {id: s1, as: maker, do: open, 说明: 打开, args: {form: F1}}\n")


@pytest.fixture
def ws_root(tmp_path):
    root = tmp_path / "ws"
    d = root / "scenarios" / "LM" / "授信申请"
    d.mkdir(parents=True)
    (root / "workspace.yaml").write_text("project: demo\n", encoding="utf-8")
    (d / "用例设计.yaml").write_text(yaml.safe_dump(DESIGN, allow_unicode=True), encoding="utf-8")
    return root


def _args(root, *a):
    return ["--workspace", str(root), "--skip-integrity", *a]


def test_cli_design_writes_a_business_readable_page(ws_root, capsys):
    assert main(_args(ws_root, "design", "LM/授信申请")) == 0
    out = capsys.readouterr().out
    page = ws_root / "reviews" / "LM-授信申请-用例设计.html"
    assert str(page) in out and "确认之前不要写场景文件" in out
    html = page.read_text(encoding="utf-8")
    for text in ("授信申请", "申请后办结", "制单人", "甲公司", "金额不一致时要不要拦？", "编号由系统生成",
                 "你确认之后，才会开始做自动化"):
        assert text in html
    assert "生成编号 &lt;R1&gt;" in html and "<R1>" not in html


def test_cli_design_accepts_the_file_path_and_reports_missing(ws_root, capsys):
    assert main(_args(ws_root, "design", str(ws_root / "scenarios" / "LM" / "授信申请" / "用例设计.yaml"))) == 0
    assert main(_args(ws_root, "design", "LM/没有这个功能")) == 2
    assert "找不到用例设计" in capsys.readouterr().err
    assert main(_args(ws_root, "design")) == 2


def test_incomplete_design_is_refused_with_every_problem_listed(tmp_path):
    bad = {"module": "LM", "cases": [{"title": "x", "kind": "主流程", "steps": [{"who": "制单人", "do": "保存"}]}],
           "rules": [{"rule": "没有依据的规则"}]}
    p = tmp_path / "用例设计.yaml"
    p.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(DesignError) as exc:
        load_design(p)
    msg = str(exc.value)
    for text in ("缺少 feature", "缺少 goal", "expect（预期结果）", "source（依据）"):
        assert text in msg


def test_design_file_is_not_treated_as_a_scenario(ws_root, capsys):
    (ws_root / "scenarios" / "LM" / "授信申请" / "演示.yaml").write_text(SCENARIO, encoding="utf-8")
    ws = load_workspace(str(ws_root))
    assert [p.name for p in ws.scenario_files()] == ["演示.yaml"]
    assert main(_args(ws_root, "list")) == 0
    out = capsys.readouterr().out
    assert "演示.yaml" in out and "无法解析" not in out and "用例设计" not in out


def test_design_page_is_organized_by_business_chain():
    d = {**DESIGN,
         "chain": {"object": "一笔授信额度", "upstream": "品种已维护", "downstream": "合同可以占用",
                   "mechanisms": ["申请和结果分开", "额度占用"]},
         "cases": [{**DESIGN["cases"][0], "form": "单一品种 12 个月", "object_from": "本用例新建"}]}
    html = render_design_html(d)
    for text in ("这个功能在业务链上的位置", "业务对象", "一笔授信额度", "品种已维护", "合同可以占用", "申请和结果分开、额度占用",
                 "业务形态", "单一品种 12 个月", "对象从哪里来", "本用例新建"):
        assert text in html
    assert "业务链上的位置" not in render_design_html(DESIGN)


def test_comma_that_cut_a_one_line_step_is_reported(tmp_path):
    p = tmp_path / "用例设计.yaml"
    p.write_text("module: LM\nfeature: 授信\ncases:\n  - title: a\n    kind: 主流程\n    goal: g\n    steps:\n"
                 "      - {who: 制单人, do: 改为 HKD 30,000 再提交, expect: 审批中}\n", encoding="utf-8")
    with pytest.raises(DesignError, match="加双引号"):
        load_design(p)


def test_chain_must_be_a_mapping(tmp_path):
    p = tmp_path / "用例设计.yaml"
    p.write_text(yaml.safe_dump({**DESIGN, "chain": "授信额度"}, allow_unicode=True), encoding="utf-8")
    with pytest.raises(DesignError, match="chain"):
        load_design(p)


def test_shipped_template_renders():
    d = load_design(TEMPLATE)
    html = render_design_html(d)
    assert "企业授信额度申请" in html and "请先确认这些问题" in html and "业务链上的位置" in html
    assert all(c.get("form") for c in d["cases"])
    assert not any("必填" in c["title"] for c in d["cases"])
    assert "HKD 30,000" in html and "HKD 90,000" in html
