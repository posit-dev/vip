"""Execution attribution for the results.json evidence record.

Answers "which pipeline execution, on which host, from which commit produced
this evidence" — the fields that make an automated test result attributable.

Every probe here degrades to None. A missing git binary, a detached worktree,
a non-repo working directory or an unrecognized CI system must never fail or
warn a verification run; provenance is not worth breaking a run over.
"""

from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_GIT_TIMEOUT_SECONDS = 5


def redact_userinfo(url: str | None) -> str | None:
    """Strip any userinfo component from a remote URL.

    CI checkouts rewrite the origin to embed a credential
    (``https://x-access-token:ghs_...@github.com/org/repo``). results.json is
    an uploaded artifact, so the credential must never reach it. Userinfo is
    never needed to identify a repository, so it is dropped unconditionally
    rather than pattern-matched against known token shapes.
    """
    if not url:
        return None
    if "://" not in url:
        # scp-style (git@host:org/repo.git). No password component, but drop
        # the user anyway so there is exactly one rule to reason about.
        return url.split("@", 1)[-1] if "@" in url else url
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        # urlsplit is lazy: it accepts "https://host:bad/x" and only raises
        # when .port parses. Both accesses must sit inside the guard, or a
        # malformed remote escapes the never-fail contract and takes down
        # report writing at the end of an otherwise good run.
        port = parts.port
    except ValueError:
        return None
    if not hostname:
        return None
    netloc = f"{hostname}:{port}" if port else hostname
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _git(args: list[str], cwd: Path) -> str | None:
    """Run a git command, returning stripped stdout, or None if it failed.

    An empty string is a valid successful result (``status --porcelain`` on a
    clean tree), so success-with-no-output must stay distinguishable from
    failure. Callers rely on that difference.
    """
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_metadata(cwd: Path, env: Mapping[str, str]) -> dict[str, Any] | None:
    commit = env.get("GITHUB_SHA") or _git(["rev-parse", "HEAD"], cwd)
    if not commit:
        return None
    status = _git(["status", "--porcelain"], cwd)
    return {
        "commit": commit,
        "branch": env.get("GITHUB_REF_NAME") or _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd),
        "dirty": bool(status) if status is not None else None,
        "remote": redact_userinfo(_git(["remote", "get-url", "origin"], cwd)),
    }


def _ci_metadata(env: Mapping[str, str]) -> dict[str, Any] | None:
    if env.get("GITHUB_ACTIONS") == "true":
        run_id = env.get("GITHUB_RUN_ID")
        repo = env.get("GITHUB_REPOSITORY")
        server = env.get("GITHUB_SERVER_URL") or "https://github.com"
        run_url = f"{server}/{repo}/actions/runs/{run_id}" if run_id and repo else None
        return {
            "provider": "github",
            "run_id": run_id,
            "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
            "run_url": run_url,
            "job": env.get("GITHUB_JOB"),
        }
    if env.get("GITLAB_CI") == "true":
        return {
            "provider": "gitlab",
            "run_id": env.get("CI_PIPELINE_ID"),
            "run_attempt": None,
            "run_url": env.get("CI_JOB_URL"),
            "job": env.get("CI_JOB_NAME"),
        }
    if env.get("JENKINS_URL"):
        return {
            "provider": "jenkins",
            "run_id": env.get("BUILD_NUMBER"),
            "run_attempt": None,
            "run_url": env.get("BUILD_URL"),
            "job": env.get("JOB_NAME"),
        }
    return None


def collect_execution_metadata(
    *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Collect host, git and CI attribution for the current run.

    ``hostname`` is the VIP runner's host, not the system under test. Anything
    rendering it must label it that way.
    """
    resolved_env = os.environ if env is None else env
    resolved_cwd = Path.cwd() if cwd is None else cwd
    return {
        "hostname": platform.node() or None,
        "git": _git_metadata(resolved_cwd, resolved_env),
        "ci": _ci_metadata(resolved_env),
    }
