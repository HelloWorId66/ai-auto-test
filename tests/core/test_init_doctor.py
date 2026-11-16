import sys
from pathlib import Path

import pytest

from ifcat import cli
from ifcat.scaffold import InitError, init_workspace
from ifcat.workspace import load_workspace


def test_init_creates_loadable_workspace_with_skill(tmp_path):
    root = tmp_path / "ws"
    created = init_workspace(root, "acme")
    ws = load_workspace(str(root))
    assert ws.project == "acme"
    skill = root / ".claude" / "skills" / "ifc-autotest" / "SKILL.md"
    assert skill.is_file() and "approve" in skill.read_text(encoding="utf-8")
    assert (root / "AGENTS.md").read_text(encoding="utf-8").count("acme") >= 1
    assert (root / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    assert "config/local/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert "workspace.yaml" in created


def test_init_keeps_machine_path_out_of_committed_files(tmp_path):
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    assert "workspace.local.yaml" in gi
    for name in ("workspace.yaml", "README.md", "AGENTS.md"):
        assert str(Path(__file__).resolve().parents[2]) not in (root / name).read_text(encoding="utf-8")


def test_init_refuses_existing_workspace_and_bad_project(tmp_path):
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    with pytest.raises(InitError):
        init_workspace(root, "acme")
    with pytest.raises(InitError):
        init_workspace(tmp_path / "x", "含 空格")


def test_refresh_updates_skill_but_keeps_user_files(tmp_path):
    root = tmp_path / "ws"
    init_workspace(root, "acme")
    (root / "AGENTS.md").write_text("我的修改", encoding="utf-8")
    skill = root / ".claude" / "skills" / "ifc-autotest" / "SKILL.md"
    skill.write_text("旧版", encoding="utf-8")
    done = init_workspace(root, "acme", refresh=True)
    assert skill.read_text(encoding="utf-8") != "旧版"
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "我的修改"
    assert any("SKILL.md" in d for d in done)


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
