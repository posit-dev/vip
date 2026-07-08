"""Selftests for the Workbench git-ops clone command construction.

Covers ``_do_clone`` in ``vip_tests.workbench.test_git_ops``: verifies the
shell command it builds removes any pre-existing clone directory before
running ``git clone``, so repeat runs against long-lived QA VMs don't fail
with "destination path already exists". No live Workbench deployment or
Playwright browser required -- ``terminal_run`` is monkeypatched to capture
the command string instead of executing it.
"""

from __future__ import annotations

from vip_tests.workbench import test_git_ops as git_ops


class _FakeGitCfg:
    def __init__(self, clone_url: str, token: str = ""):
        self.clone_url = clone_url
        self.token = token


def test_do_clone_removes_existing_dir_before_cloning(monkeypatch):
    captured: dict = {}

    def fake_terminal_run(page, cmd, timeout=30_000, *, readback_lang="r"):
        captured["cmd"] = cmd
        return ""

    monkeypatch.setattr(git_ops, "terminal_run", fake_terminal_run)

    git_cfg = _FakeGitCfg("https://github.com/example/jumpstart_examples.git")
    git_session_ctx: dict = {}

    clone_dir = git_ops._do_clone(object(), git_session_ctx, git_cfg, readback_lang="r")

    assert clone_dir == "/tmp/jumpstart_examples"
    assert git_session_ctx["clone_dir"] == clone_dir
    rm_index = captured["cmd"].find("rm -rf /tmp/jumpstart_examples")
    clone_index = captured["cmd"].find("git clone")
    assert rm_index != -1, f"expected rm -rf of clone dir in command: {captured['cmd']!r}"
    assert rm_index < clone_index, "rm -rf must run before git clone"


def test_do_clone_uses_custom_workdir(monkeypatch):
    captured: dict = {}

    def fake_terminal_run(page, cmd, timeout=30_000, *, readback_lang="r"):
        captured["cmd"] = cmd
        return ""

    monkeypatch.setattr(git_ops, "terminal_run", fake_terminal_run)

    git_cfg = _FakeGitCfg("https://github.com/example/other-repo.git")
    clone_dir = git_ops._do_clone(
        object(), {}, git_cfg, readback_lang="python", workdir="/home/vip"
    )

    assert clone_dir == "/home/vip/other-repo"
    assert "rm -rf /home/vip/other-repo" in captured["cmd"]
