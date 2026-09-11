"""Execution attribution for the results.json evidence record.

Answers "which pipeline execution, on which host, from which commit produced
this evidence" — the fields that make an automated test result attributable.

Every probe here degrades to None. A missing git binary, a detached worktree,
a non-repo working directory or an unrecognized CI system must never fail or
warn a verification run; provenance is not worth breaking a run over.
"""

from __future__ import annotations

import getpass
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
        #
        # Require the full scp shape rather than just an "@": a local path may
        # legitimately contain one, and stripping on the "@" alone rewrites
        # repo@2.git to 2.git and releases@2026/repo.git to 2026/repo.git,
        # corrupting a provenance remote to remove a credential that was never
        # there. scp syntax is user@host:path, so the host part must carry a
        # colon before any slash.
        user, sep, rest = url.partition("@")
        if not sep or "/" in user:
            return url
        host = rest.split("/", 1)[0]
        return rest if ":" in host else url
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        # urlsplit is lazy: it accepts "https://host:bad/x" and only raises
        # when .port parses. Both accesses must sit inside the guard, or a
        # malformed remote escapes the never-fail contract and takes down
        # report writing at the end of an otherwise good run.
        port = parts.port
        has_userinfo = parts.username is not None or parts.password is not None
    except ValueError:
        return None
    # Nothing to redact means nothing to rebuild. Returning the URL untouched
    # is what keeps a host-less remote intact: file:///srv/git/repo.git has no
    # hostname, and rebuilding it from the decomposed parts would drop it to
    # None -- deleting provenance from an evidence record to strip a
    # credential that was never there.
    if not has_userinfo:
        return url
    if not hostname:
        return None
    # An IPv6 literal must keep its brackets or the port fuses into the
    # address: [2001:db8::1]:8443 would otherwise rebuild as 2001:db8::1:8443,
    # which no longer parses back to a host.
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port else host
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
            # Decode explicitly rather than via text=True, which uses the
            # locale codec with errors="strict". Branch names and remote URLs
            # come out of git config as raw bytes, so a non-ASCII one on a
            # cp1252/cp932 host raises UnicodeDecodeError -- a ValueError, not
            # caught below, which would escape this module's never-fail
            # contract and take the whole report write down with it.
            encoding="utf-8",
            errors="replace",
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


def _performed_by(env: Mapping[str, str]) -> dict[str, Any] | None:
    """Who ran this verification.

    FDA's Computer Software Assurance guidance asks for a record of who
    performed the testing alongside the date. Every other field in this module
    identifies a *machine* or a *commit*, which answers "which execution" but
    not "which person is accountable for it".

    Resolution order, most deliberate first: ``VIP_PERFORMED_BY`` names the
    person on whose behalf the run happens, which is what a QA engineer
    kicking off a scheduled pipeline needs to record; then the CI system's own
    actor; then the local login. ``source`` travels with the value because an
    auditor reading "svc-vip-runner" needs to know whether a human typed that
    or a service account inherited it.
    """
    explicit = (env.get("VIP_PERFORMED_BY") or "").strip()
    if explicit:
        return {"identity": explicit, "source": "explicit"}
    for var, source in (
        ("GITHUB_ACTOR", "github"),
        ("GITLAB_USER_LOGIN", "gitlab"),
        ("BUILD_USER_ID", "jenkins"),
    ):
        value = (env.get(var) or "").strip()
        if value:
            return {"identity": value, "source": source}
    try:
        login = getpass.getuser().strip()
    except Exception:
        # getpass.getuser() raises on a container with no passwd entry and no
        # LOGNAME/USER/LNAME/USERNAME set. Same never-fail contract as the rest
        # of this module.
        return None
    return {"identity": login, "source": "login"} if login else None


def collect_execution_metadata(
    *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Collect host, git and CI attribution for the current run.

    ``hostname`` is the VIP runner's host, not the system under test. Anything
    rendering it must label it that way.

    ``performed_by`` records an operator identity, so the whole block is what
    ``--vip-no-attribution`` exists to omit for anyone who does not want that
    written into an archived artifact.
    """
    resolved_env = os.environ if env is None else env
    if cwd is None:
        # Path.cwd() raises FileNotFoundError when the working directory has
        # been removed underneath the process -- a fixture that deletes its own
        # cwd, or a CI step unmounting the workspace. Unguarded it escapes this
        # module's never-fail contract.
        try:
            resolved_cwd: Path | None = Path.cwd()
        except OSError:
            resolved_cwd = None
    else:
        resolved_cwd = cwd
    return {
        "hostname": platform.node() or None,
        # No cwd means no directory to resolve a repository against, so skip
        # git rather than hand subprocess a None it would reject.
        "git": _git_metadata(resolved_cwd, resolved_env) if resolved_cwd is not None else None,
        "ci": _ci_metadata(resolved_env),
        "performed_by": _performed_by(resolved_env),
    }
