import json
import subprocess

import pytest

from vip.attribution import collect_execution_metadata


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
