import sys
from pathlib import Path

import pytest

from ifcat import cli
from ifcat.scaffold import InitError, init_workspace
from ifcat.workspace import load_workspace


def test_init_creates_loadable_workspace(tmp_path):
    root = tmp_path / "ws"
    created = init_workspace(root, "acme")
    ws = load_workspace(str(root))
    assert ws.project == "acme"
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "acme" in agents and "ifc-autotest" in agents
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    assert "config/local/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert "workspace.yaml" in created
    assert (root / "config" / "local" / "dev.yaml.example").is_file()
    assert (root / "probes" / "标定探针示例.yaml").is_file()


def test_init_does_not_copy_skill_or_machine_paths_into_workspace(tmp_path):
    """规程随技能分发；工作区里不放它的副本，也不写本机路径。"""
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    assert not (root / ".claude").exists()
    assert not (root / "workspace.local.yaml").exists()
    for p in root.rglob("*"):
        if p.is_file():
            assert str(Path(__file__).resolve().parents[2]) not in p.read_text(encoding="utf-8")


def test_init_refuses_existing_workspace_and_bad_project(tmp_path):
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    with pytest.raises(InitError):
        init_workspace(root, "acme")
    with pytest.raises(InitError):
        init_workspace(tmp_path / "x", "含 空格")


def test_refresh_only_adds_missing_files(tmp_path, capsys):
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    (root / "AGENTS.md").write_text("我的修改", encoding="utf-8")
    (root / "CLAUDE.md").unlink()
    old = root / ".claude" / "skills" / "ifc-autotest"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("旧版", encoding="utf-8")

    assert cli.main(["init", str(root), "--refresh", "--skip-integrity"]) == 0
    out = capsys.readouterr().out
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "我的修改"
    assert (root / "CLAUDE.md").is_file()
    assert (old / "SKILL.md").read_text(encoding="utf-8") == "旧版"  # 不替用户删东西，只提示
    assert "旧版本留下的规程副本" in out


def test_doctor_reports_missing_env_config(tmp_path, capsys):
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    code = cli.main(["doctor", "--workspace", str(root), "--skip-integrity"])
    out = capsys.readouterr().out
    assert code == 1
    assert "未通过  环境配置" in out and "怎么办" in out


def test_cli_init_command(tmp_path, capsys):
    code = cli.main(["init", str(tmp_path / "w"), "--project", "p1", "--skip-integrity"])
    assert code == 0
    assert (tmp_path / "w" / "workspace.yaml").is_file()
    assert cli.main(["init", str(tmp_path / "w"), "--skip-integrity"]) == 2
