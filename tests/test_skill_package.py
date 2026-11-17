"""技能发布件：打包后的目录不依赖开发仓库，用它的启动脚本就能完成新建工作区到生成审核页。"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ifcat import CORE_VERSION

ROOT = Path(__file__).resolve().parents[1]
FORM = ('{"formID": "F1", "formName": "演示", "version": "React", "components": [{"key": "Root", "type": "FormBoxContainer", '
        '"props": {}, "children": [{"key": "A", "type": "FormTextInput", "props": {"showLabelText": "名称", '
        '"dataSetID": "T1", "dataSetColID": "F_NAME"}}]}], "dataModels": [], "actionComps": []}')
SCENARIO = """
id: XX-演示
title: 演示
module: XX
goal: 演示
roles: {maker: 制单员}
steps:
  - {id: s1, as: maker, do: open, 说明: 打开, args: {form: F1}}
  - {id: s2, as: maker, do: fill, 说明: 填写, args: {form: F1, values: {名称: "演示-${unique}"}}}
  - {id: c1, as: maker, do: expect_field, 说明: 名称保留, args: {form: F1, label: 名称, expected: "演示"}}
"""


def _builder():
    spec = importlib.util.spec_from_file_location("build_skill", ROOT / "tools" / "build_skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def skill(tmp_path_factory):
    return _builder().build(tmp_path_factory.mktemp("dist"))


def _ifc(skill: Path, *args: str, cwd: Path):
    # IFCAT_PYTHON 让启动脚本直接用当前解释器，自测里不重新下载依赖和浏览器
    env = {**os.environ, "IFCAT_PYTHON": sys.executable, "IFCAT_HOME": str(cwd / "home")}
    env.pop("IFCAT_WORKSPACE", None)
    return subprocess.run([sys.executable, str(skill / "scripts" / "ifc.py"), *args], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8")


def test_package_is_self_contained(skill):
    assert (skill / "VERSION").read_text(encoding="utf-8").strip() == CORE_VERSION
    for rel in ("SKILL.md", "scripts/ifc.py", "references/写场景.md", "references/场景模板.yaml", "references/用例设计模板.yaml",
                "engine/ifc.py", "engine/core/ifcat/MANIFEST.json", "engine/requirements.lock",
                "engine/templates/workspace/workspace.yaml", "engine/ui/server.py", "engine/tools/db_mcp.py"):
        assert (skill / rel).is_file(), rel
    names = {p.name for p in skill.rglob("*")}
    assert not names & {"__pycache__", "tests", "release_manifest.py", "build_skill.py", ".venv"}


def test_skill_docs_only_point_to_files_in_the_package(skill):
    import re

    for doc in [skill / "SKILL.md", *sorted((skill / "references").glob("*.md"))]:
        for ref in re.findall(r"`(references/[^`]+)`", doc.read_text(encoding="utf-8")):
            assert (skill / ref).is_file(), f"{doc.name} 指向不存在的 {ref}"


def test_packaged_skill_works_without_the_repo(skill, tmp_path):
    ws = tmp_path / "ws"
    r = _ifc(skill, "init", str(ws), "--project", "demo", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert not (ws / ".claude").exists() and not (ws / "workspace.local.yaml").exists()
    assert "ifc-autotest" in (ws / "AGENTS.md").read_text(encoding="utf-8")
    (ws / "knowledge" / "forms" / "F1.json").write_text(FORM, encoding="utf-8")
    (ws / "scenarios" / "XX").mkdir(parents=True)
    (ws / "scenarios" / "XX" / "演示.yaml").write_text(SCENARIO, encoding="utf-8")

    r = _ifc(skill, "validate", "--all", cwd=ws)  # 在工作区目录里运行，不用给 --workspace
    assert r.returncode == 0, r.stdout + r.stderr
    r = _ifc(skill, "render", "演示", cwd=ws)
    assert r.returncode == 0, r.stdout + r.stderr
    assert list((ws / "reviews").glob("*.html"))
    r = _ifc(skill, "version", cwd=ws)
    assert r.returncode == 0 and CORE_VERSION in r.stdout


def test_packaged_template_scenario_is_valid_yaml_with_known_actions(skill):
    import yaml

    from ifcat.scenario import parse_scenario

    sc = parse_scenario(yaml.safe_load((skill / "references" / "场景模板.yaml").read_text(encoding="utf-8")))
    assert sc.feature and sc.kind == "主流程" and len(sc.steps) >= 5


def test_launcher_passes_exit_code_and_rejects_unknown_tool(skill, tmp_path):
    assert _ifc(skill, "list", "--workspace", str(tmp_path / "nowhere"), cwd=tmp_path).returncode == 2
    assert _ifc(skill, "tool", "rm", cwd=tmp_path).returncode == 2


def test_build_refuses_when_core_was_changed(tmp_path, monkeypatch):
    mod = _builder()
    from ifcat import guard

    def broken():
        raise guard.IntegrityError("被改动：x.py")

    monkeypatch.setattr(mod.guard, "verify_integrity", broken)
    assert mod.main(["--out", str(tmp_path)]) == 2
    assert not (tmp_path / "ifc-autotest").exists()
