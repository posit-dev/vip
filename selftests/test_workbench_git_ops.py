"""Selftests for the Workbench git-ops clone command construction and skip gates.

Covers ``_do_clone`` in ``vip_tests.workbench.test_git_ops``: verifies the
shell command it builds removes any pre-existing clone directory before
running ``git clone``, so repeat runs against long-lived QA VMs don't fail
with "destination path already exists". No live Workbench deployment or
Playwright browser required -- ``terminal_run`` is monkeypatched to capture
the command string instead of executing it.

Also covers the config/auth skip-gate wording (#483) and the Gherkin step
order guard (#479): every scenario in test_git_ops.feature must resolve the
Git config gate before attempting the (possibly flaky) login step, so a
read-only/config situation is reported deterministically instead of being
masked by a login bounce.
"""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path

import pytest

from vip.config import GitTestConfig, VIPConfig, WorkbenchConfig
from vip.gherkin import parse_feature_file
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


# ---------------------------------------------------------------------------
# #479 -- Gherkin step order guard
# ---------------------------------------------------------------------------


def _git_ops_feature_path() -> Path:
    spec = find_spec("vip_tests")
    assert spec and spec.submodule_search_locations
    return Path(spec.submodule_search_locations[0]) / "workbench" / "test_git_ops.feature"


class TestFeatureStepOrder:
    """The Git config gate must resolve before the (possibly flaky) login step.

    Otherwise a read-only/config situation is masked by a non-deterministic
    login bounce, surfacing a misleading auth error instead of the real
    config/read-only reason (#479).
    """

    def test_config_gate_precedes_login_in_every_scenario(self):
        parsed = parse_feature_file(_git_ops_feature_path())
        assert parsed["scenarios"], "expected scenarios in test_git_ops.feature"
        for scenario in parsed["scenarios"]:
            steps = scenario["steps"]
            config_idx = next(
                i for i, s in enumerate(steps) if "the Git test config is available" in s
            )
            login_idx = next(
                i for i, s in enumerate(steps) if "Workbench is accessible and I am logged in" in s
            )
            assert config_idx < login_idx, (
                f"scenario {scenario['title']!r}: 'the Git test config is available' "
                f"must precede 'Workbench is accessible and I am logged in', "
                f"got steps: {steps}"
            )

    def test_push_scenarios_check_pushing_before_login(self):
        parsed = parse_feature_file(_git_ops_feature_path())
        push_scenarios = [s for s in parsed["scenarios"] if "push" in s["title"].lower()]
        assert push_scenarios, "expected at least one push scenario"
        for scenario in push_scenarios:
            steps = scenario["steps"]
            pushing_idx = next(
                i for i, s in enumerate(steps) if "the Git test config supports pushing" in s
            )
            login_idx = next(
                i for i, s in enumerate(steps) if "Workbench is accessible and I am logged in" in s
            )
            assert pushing_idx < login_idx, (
                f"scenario {scenario['title']!r}: 'the Git test config supports pushing' "
                f"must precede 'Workbench is accessible and I am logged in', "
                f"got steps: {steps}"
            )


# ---------------------------------------------------------------------------
# #483 -- skip-message wording
# ---------------------------------------------------------------------------


def _make_vip_config(git_test: GitTestConfig | None) -> VIPConfig:
    wc = WorkbenchConfig(url="https://workbench.example.com", git_test=git_test)
    return VIPConfig(workbench=wc)


class TestGitConfigAvailableSkipMessages:
    def test_none_config_message_explains_public_vs_token(self):
        """Defensive fallback: git_test is None only via direct construction."""
        cfg = _make_vip_config(None)
        with pytest.raises(pytest.skip.Exception) as exc_info:
            git_ops.git_config_available(cfg)
        msg = exc_info.value.msg
        assert "auth_method='none'" in msg
        assert "no token required" in msg
        assert "VIP_GIT_TOKEN" in msg

    def test_empty_clone_url_message_explains_public_vs_token(self):
        cfg = _make_vip_config(GitTestConfig(clone_url="", auth_method="none"))
        with pytest.raises(pytest.skip.Exception) as exc_info:
            git_ops.git_config_available(cfg)
        msg = exc_info.value.msg
        assert "auth_method='none'" in msg
        assert "no token" in msg

    def test_valid_none_config_does_not_skip(self):
        cfg = _make_vip_config(
            GitTestConfig(
                clone_url="https://github.com/posit-dev/posit-cli.git", auth_method="none"
            )
        )
        result = git_ops.git_config_available(cfg)
        assert result is cfg.workbench.git_test


class TestGitConfigSupportsPushingSkipMessage:
    def test_anonymous_auth_skip_message(self):
        git_cfg = GitTestConfig(clone_url="https://github.com/org/repo.git", auth_method="none")
        with pytest.raises(pytest.skip.Exception) as exc_info:
            git_ops.git_config_supports_pushing(git_cfg)
        msg = exc_info.value.msg
        assert "auth_method='none' is anonymous (read-only)" in msg
        assert "auth_method='https-token'" in msg
        assert "VIP_GIT_TOKEN" in msg

    def test_https_token_auth_does_not_skip(self):
        git_cfg = GitTestConfig(
            clone_url="https://github.com/org/repo.git", auth_method="https-token", token="tok"
        )
        # Should not raise/skip.
        git_ops.git_config_supports_pushing(git_cfg)
