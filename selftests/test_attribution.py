import json
import subprocess
import sys
from pathlib import Path

import pytest

from vip.attribution import (
    _git,
    _performed_by,
    collect_execution_metadata,
    redact_userinfo,
)


def _init_repo(path):
    def git(*args):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)

    git("init")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "Test")
    git("config", "commit.gpgsign", "false")
    (path / "f.txt").write_text("hello")
    git("add", "f.txt")
    git("commit", "-m", "initial")


def test_git_metadata_from_a_real_repo(tmp_path):
    _init_repo(tmp_path)
    meta = collect_execution_metadata(cwd=tmp_path, env={})
    assert meta["git"]["commit"] is not None
    assert len(meta["git"]["commit"]) == 40
    assert meta["git"]["dirty"] is False


def test_dirty_worktree_is_reported(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "f.txt").write_text("changed")
    assert collect_execution_metadata(cwd=tmp_path, env={})["git"]["dirty"] is True


def test_non_repo_yields_null_git(tmp_path):
    assert collect_execution_metadata(cwd=tmp_path, env={})["git"] is None


def test_no_ci_env_yields_null_ci(tmp_path):
    assert collect_execution_metadata(cwd=tmp_path, env={})["ci"] is None


def test_github_actions_run_url_is_composed(tmp_path):
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_RUN_ID": "42",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "posit-dev/vip",
        "GITHUB_JOB": "connect-smoke",
    }
    ci = collect_execution_metadata(cwd=tmp_path, env=env)["ci"]
    assert ci["provider"] == "github"
    assert ci["run_url"] == "https://github.com/posit-dev/vip/actions/runs/42"
    assert ci["job"] == "connect-smoke"


def test_gitlab_and_jenkins_are_recognized(tmp_path):
    gl = collect_execution_metadata(
        cwd=tmp_path, env={"GITLAB_CI": "true", "CI_JOB_URL": "https://gl/x/-/jobs/9"}
    )["ci"]
    assert gl["provider"] == "gitlab"
    assert gl["run_url"] == "https://gl/x/-/jobs/9"

    jk = collect_execution_metadata(
        cwd=tmp_path, env={"JENKINS_URL": "https://j/", "BUILD_URL": "https://j/job/x/7/"}
    )["ci"]
    assert jk["provider"] == "jenkins"
    assert jk["run_url"] == "https://j/job/x/7/"


def test_env_sha_takes_precedence_over_subprocess(tmp_path):
    _init_repo(tmp_path)
    env = {"GITHUB_SHA": "a" * 40, "GITHUB_REF_NAME": "feature/x"}
    meta = collect_execution_metadata(cwd=tmp_path, env=env)
    assert meta["git"]["commit"] == "a" * 40
    assert meta["git"]["branch"] == "feature/x"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://x-access-token:ghs_SECRET@github.com/o/r", "https://github.com/o/r"),
        ("https://user:pw@example.com:8443/o/r.git", "https://example.com:8443/o/r.git"),
        ("https://github.com/o/r", "https://github.com/o/r"),
        ("git@github.com:o/r.git", "github.com:o/r.git"),
        # urlsplit accepts this and only raises when .port is read.
        ("https://example.com:bad/repo", None),
        ("", None),
        (None, None),
    ],
)
def test_userinfo_is_redacted(raw, expected):
    from vip.attribution import redact_userinfo

    assert redact_userinfo(raw) == expected


def test_hostname_is_recorded(tmp_path):
    assert collect_execution_metadata(cwd=tmp_path, env={})["hostname"]


def test_no_attribution_flag_omits_the_block(pytester):
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess(
        "--vip-report", str(report), "--vip-no-attribution", "-p", "no:cacheprovider"
    )
    assert json.loads(report.read_text())["execution"] is None


def test_credential_in_remote_never_reaches_the_file(pytester, monkeypatch):
    """Regression guard: assert the token is absent from the whole file."""
    secret = "ghs_THISMUSTNOTAPPEAR"
    subprocess.run(["git", "init"], cwd=pytester.path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://x-access-token:{secret}@github.com/o/r"],
        cwd=pytester.path,
        check=True,
        capture_output=True,
    )
    for key, value in (
        ("user.email", "t@example.com"),
        ("user.name", "T"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(
            ["git", "config", key, value], cwd=pytester.path, check=True, capture_output=True
        )
    pytester.makepyfile(test_x="def test_ok(): assert True")
    subprocess.run(["git", "add", "-A"], cwd=pytester.path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "c"], cwd=pytester.path, check=True, capture_output=True)

    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")
    assert secret not in report.read_text()


class TestNeverFails:
    """The module's contract: a probe failure must never break a run.

    These sit at the top of a chain that ends in results.json, junit.xml,
    results.sarif and failures.json all going unwritten -- attribution is
    collected while building the payload, above the try/except that writes it.
    """

    def test_deleted_working_directory_degrades_instead_of_raising(self, tmp_path, monkeypatch):
        def boom():
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(Path, "cwd", staticmethod(boom))
        meta = collect_execution_metadata(env={})
        assert meta["git"] is None
        assert meta["hostname"] is not None

    def test_undecodable_git_output_does_not_raise(self, tmp_path, monkeypatch):
        """text=True would decode with the locale codec and errors='strict'."""
        import subprocess

        real_run = subprocess.run

        def fake_run(args, **kwargs):
            assert kwargs.get("encoding") == "utf-8"
            assert kwargs.get("errors") == "replace"
            return real_run([sys.executable, "-c", "print('ok')"], **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert _git(["rev-parse", "HEAD"], tmp_path) == "ok"


class TestRedactUserinfoEdgeCases:
    def test_ipv6_host_keeps_its_brackets(self):
        assert redact_userinfo("https://u:p@[2001:db8::1]:8443/o/r.git") == (
            "https://[2001:db8::1]:8443/o/r.git"
        )

    def test_hostless_remote_is_preserved(self):
        """file:// has no hostname and no credential; dropping it deletes provenance."""
        assert redact_userinfo("file:///srv/git/repo.git") == "file:///srv/git/repo.git"

    @pytest.mark.parametrize(
        "url",
        [
            "/srv/git/repo@2.git",
            # Relative local paths: an "@" alone is not userinfo. scp syntax is
            # user@host:path, so without a colon in the host there is nothing
            # to strip.
            "repo@2.git",
            "releases@2026/repo.git",
        ],
    )
    def test_path_containing_an_at_sign_is_not_truncated(self, url):
        assert redact_userinfo(url) == url

    def test_scp_style_still_strips_the_user(self):
        assert redact_userinfo("git@github.com:org/repo.git") == "github.com:org/repo.git"

    def test_credentialless_url_is_returned_unchanged(self):
        assert redact_userinfo("https://github.com/org/repo.git") == (
            "https://github.com/org/repo.git"
        )


class TestPerformedBy:
    """Who ran the verification.

    FDA's Computer Software Assurance guidance asks the record of an assurance
    activity to carry who performed the testing alongside the date. Every other
    field this module collects identifies a machine or a commit.
    """

    def test_explicit_override_wins_over_every_ci_actor(self):
        env = {"VIP_PERFORMED_BY": "QA Lead", "GITHUB_ACTOR": "octocat"}
        assert _performed_by(env) == {"identity": "QA Lead", "source": "explicit"}

    def test_whitespace_only_override_falls_through(self):
        """An empty variable exported by a shell must not shadow the real actor."""
        env = {"VIP_PERFORMED_BY": "   ", "GITHUB_ACTOR": "octocat"}
        assert _performed_by(env) == {"identity": "octocat", "source": "github"}

    @pytest.mark.parametrize(
        ("var", "source"),
        [("GITHUB_ACTOR", "github"), ("GITLAB_USER_LOGIN", "gitlab"), ("BUILD_USER_ID", "jenkins")],
    )
    def test_each_ci_actor_is_recognized_with_its_source(self, var, source):
        assert _performed_by({var: "runner"}) == {"identity": "runner", "source": source}

    def test_local_login_is_the_last_resort_and_says_so(self, monkeypatch):
        monkeypatch.setattr("vip.attribution.getpass.getuser", lambda: "bdeitte")
        assert _performed_by({}) == {"identity": "bdeitte", "source": "login"}

    def test_an_unresolvable_login_degrades_to_none(self, monkeypatch):
        """No passwd entry and no LOGNAME/USER set -- a bare container."""

        def boom():
            raise KeyError("uid not found")

        monkeypatch.setattr("vip.attribution.getpass.getuser", boom)
        assert _performed_by({}) is None

    def test_collect_execution_metadata_carries_the_performer(self, tmp_path):
        meta = collect_execution_metadata(cwd=tmp_path, env={"VIP_PERFORMED_BY": "QA Lead"})
        assert meta["performed_by"] == {"identity": "QA Lead", "source": "explicit"}
