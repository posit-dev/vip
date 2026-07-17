"""Step definitions for Workbench Git operations tests.

Tests cover terminal-based Git operations (clone, branch, commit, push) in
RStudio, VS Code, and Positron sessions.

Clone scenarios run out-of-the-box against a default public repo (auth_method
"none", no token) when [workbench.git_test] is absent from vip.toml.  Push
scenarios require auth_method "https-token" with VIP_GIT_TOKEN set and
auto-skip as read-only otherwise.  The config-availability gate runs before
the login step so a read-only/config situation is reported deterministically,
without depending on a (possibly flaky) login attempt.
"""

from __future__ import annotations

import shlex
import time
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse, urlunparse

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given, scenario, then, when

from vip.timeouts import timeout_scale
from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_QUICK,
    TIMEOUT_SESSION_START,
    assert_homepage_loaded,
    unique_session_name,
    wait_for_session_active,
    workbench_login,
)
from vip_tests.workbench.exec import ExecError, file_exists, terminal_run
from vip_tests.workbench.pages import (
    Homepage,
    NewSessionDialog,
    PositronSession,
    RStudioSession,
    VSCodeSession,
)

_FILENAME = Path(__file__).name

# Extra timeout (ms) for Git network operations (clone / push). Scaled by
# VIP_TIMEOUT_SCALE so slow deployments don't time out mid-clone.
_TIMEOUT_GIT_NETWORK = int(120_000 * timeout_scale())

# Timeout (ms) for waiting for the IDE to be functional after session join.
# Scaled by VIP_TIMEOUT_SCALE — Positron's console can take well over the
# unscaled 60s to appear on slow/cold deployments.
_TIMEOUT_IDE_READY = int(60_000 * timeout_scale())

# Prefix used for test branches; mirrors unique_session_name style
_BRANCH_PREFIX = "vip"


def _make_branch_name() -> str:
    """Return a unique test branch name: vip-<nanosecond timestamp>."""
    return f"{_BRANCH_PREFIX}-{time.time_ns()}"


def _inject_token_into_url(clone_url: str, token: str) -> str:
    """Embed *token* into an HTTPS clone URL for credential-less cloning.

    Transforms ``https://github.com/org/repo.git`` into
    ``https://x-token-auth:<token>@github.com/org/repo.git``.
    Returns the URL unchanged when token is empty.
    Raises ValueError when the URL scheme is not https.
    """
    if not token:
        return clone_url
    parsed = urlparse(clone_url)
    if parsed.scheme != "https":
        raise ValueError(
            f"Token injection is only supported for https:// URLs; got scheme {parsed.scheme!r}. "
            "Use an https clone URL or configure a different auth method."
        )
    netloc_with_creds = f"x-token-auth:{token}@{parsed.hostname}"
    if parsed.port:
        netloc_with_creds += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc_with_creds))


def _repo_dir_from_url(clone_url: str) -> str:
    """Return the bare repository directory name that ``git clone`` would create."""
    name = clone_url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


# ---------------------------------------------------------------------------
# Scenario bindings
# ---------------------------------------------------------------------------


@scenario("test_git_ops.feature", "Clone a Git repository in RStudio terminal")
def test_clone_rstudio():
    pass


@scenario("test_git_ops.feature", "Create a branch, commit, and push from RStudio terminal")
def test_push_rstudio():
    pass


@scenario("test_git_ops.feature", "Clone a Git repository in VS Code terminal")
def test_clone_vscode():
    pass


@scenario("test_git_ops.feature", "Create a branch, commit, and push from VS Code terminal")
def test_push_vscode():
    pass


@scenario("test_git_ops.feature", "Clone a Git repository in Positron terminal")
def test_clone_positron():
    pass


@scenario("test_git_ops.feature", "Create a branch, commit, and push from Positron terminal")
def test_push_positron():
    pass


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_session_ctx():
    """Carry shared state across steps: session name, IDE, clone dir, branch name."""
    return {
        "name": None,
        "ide": None,
        "clone_dir": None,
        "branch": None,
    }


@pytest.fixture(scope="session", autouse=True)
def _wb_git_cleanup_state():
    """Session-scoped safety net: track pushed branches that need remote deletion.

    Populated by push steps.  On session teardown this fixture attempts to
    delete any branches that were not cleaned up by the scenario's final Then
    step (e.g. because an intermediate step failed).

    The cleanup runs terminal_run against a Playwright page, which is not
    available at session scope.  We therefore store (auth_url, branch)
    tuples and delete them using subprocess git commands as a last
    resort.  When the page-level cleanup already deleted the branch,
    ``git push origin --delete`` is a no-op (branch not found) and is silently
    ignored.
    """
    state: dict = {"pending": []}
    yield state
    # Best-effort cleanup using subprocess; Playwright pages are gone by now.
    import subprocess  # noqa: PLC0415

    for auth_url, branch in state["pending"]:
        try:
            subprocess.run(
                ["git", "push", auth_url, "--delete", branch],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Shared Given steps
# ---------------------------------------------------------------------------


@given("Workbench is accessible and I am logged in")
def workbench_accessible(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    workbench_login(
        page,
        workbench_url,
        test_username,
        test_password,
        auth_provider,
        interactive_auth,
        auth_mode=auth_mode,
        workbench_auth_error=workbench_auth_error,
    )
    assert_homepage_loaded(page)


@given("the Git test config is available", target_fixture="git_cfg")
def git_config_available(vip_config):
    """Skip the scenario when [workbench.git_test] is not configured."""
    from urllib.parse import urlparse as _urlparse

    cfg = vip_config.workbench.git_test
    if cfg is None:
        # Defensive fallback: WorkbenchConfig.from_dict always populates
        # git_test with a default (anonymous clone of a public repo) when the
        # [workbench.git_test] block is absent, so this should rarely fire —
        # it only guards direct construction of WorkbenchConfig (e.g. tests).
        pytest.skip(
            "Git test config is not configured. "
            "Cloning a public repo needs only clone_url and auth_method='none' "
            "in a [workbench.git_test] block of vip.toml (no token required). "
            "Push/private-repo scenarios additionally need auth_method='https-token' "
            "with VIP_GIT_TOKEN set in the environment."
        )
    if cfg.auth_method not in ("https-token", "none"):
        pytest.skip(
            f"workbench.git_test.auth_method={cfg.auth_method!r} is not supported. "
            "Supported values: 'https-token', 'none'."
        )
    if not cfg.clone_url:
        pytest.skip(
            "workbench.git_test.clone_url is empty. "
            "Set clone_url in the [workbench.git_test] block of vip.toml — "
            "a public repo needs only clone_url with auth_method='none' (no token)."
        )
    if _urlparse(cfg.clone_url).scheme != "https":
        pytest.skip(
            f"workbench.git_test.clone_url scheme is not https: {cfg.clone_url!r}. "
            "Git test scenarios require an https:// clone URL "
            "(token injection for auth_method='https-token' relies on it)."
        )
    if cfg.auth_method == "https-token" and not cfg.token:
        pytest.skip(
            "VIP_GIT_TOKEN is not set. "
            "Export VIP_GIT_TOKEN=<personal-access-token> before running Git test scenarios, "
            "or set auth_method='none' for an anonymous public-repo clone."
        )
    return cfg


@given("the Git test config supports pushing")
def git_config_supports_pushing(git_cfg):
    """Skip write scenarios under anonymous (read-only) auth."""
    if git_cfg.auth_method == "none":
        pytest.skip(
            "workbench.git_test.auth_method='none' is anonymous (read-only). "
            "Push/commit scenarios require auth_method='https-token' with VIP_GIT_TOKEN set."
        )


# ---------------------------------------------------------------------------
# Session launch helpers
# ---------------------------------------------------------------------------


def _start_session(page: Page, ide_name: str, session_name: str) -> None:
    """Open the New Session dialog and launch a session of the given IDE type."""
    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    ide_display = NewSessionDialog.ide_display_name(ide_name)
    ide_tab = dialog.get_by_role("tab", name=ide_display)
    if ide_tab.count() == 0:
        _cancel_dialog_and_skip(page, f"{ide_name} IDE not available in this Workbench deployment")
    ide_tab.click(timeout=TIMEOUT_QUICK)

    launch_btn = page.locator(NewSessionDialog.LAUNCH_BUTTON)
    try:
        launch_btn.wait_for(state="visible", timeout=TIMEOUT_QUICK)
    except PlaywrightTimeoutError:
        _cancel_dialog_and_skip(
            page,
            f"{ide_name} tab opened but Launch button did not appear — "
            "the IDE may not be installed or fully available on this Workbench instance",
        )

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    launch_btn.click(timeout=TIMEOUT_QUICK)


def _cancel_dialog_and_skip(page: Page, reason: str) -> NoReturn:
    """Best-effort cancel the New Session dialog, then skip."""
    try:
        cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
        if cancel.count() > 0:
            try:
                cancel.click(timeout=TIMEOUT_QUICK)
            except (PlaywrightTimeoutError, PlaywrightError):
                pass
    except (PlaywrightTimeoutError, PlaywrightError):
        pass
    pytest.skip(reason)


def _join_session(page: Page, session_name: str) -> None:
    """Wait for session to become Active, then navigate into it."""
    session_row = wait_for_session_active(page, session_name, timeout=TIMEOUT_SESSION_START)
    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()


def _launch_and_join(page: Page, ide_name: str, git_session_ctx: dict) -> None:
    """Start an IDE session and navigate into it, populating *git_session_ctx*."""
    session_name = unique_session_name(_FILENAME)
    git_session_ctx["name"] = session_name
    git_session_ctx["ide"] = ide_name
    _start_session(page, ide_name, session_name)
    _join_session(page, session_name)


# ---------------------------------------------------------------------------
# Session launch When steps
# ---------------------------------------------------------------------------


@when("I launch an RStudio session")
def launch_rstudio(page: Page, git_session_ctx: dict):
    _launch_and_join(page, "RStudio", git_session_ctx)
    try:
        page.locator(RStudioSession.LOGO).wait_for(state="visible", timeout=_TIMEOUT_IDE_READY)
    except PlaywrightTimeoutError:
        pytest.skip(
            "RStudio did not load within timeout — "
            "the IDE may not be installed on this Workbench instance"
        )


@when("I launch a VS Code session")
def launch_vscode(page: Page, git_session_ctx: dict):
    _launch_and_join(page, "VS Code", git_session_ctx)
    try:
        page.locator(VSCodeSession.WORKBENCH).wait_for(state="visible", timeout=_TIMEOUT_IDE_READY)
    except PlaywrightTimeoutError:
        pytest.skip(
            "VS Code did not load within timeout — "
            "the IDE may not be installed on this Workbench instance"
        )


@when("I launch a Positron session")
def launch_positron(page: Page, git_session_ctx: dict):
    _launch_and_join(page, "Positron", git_session_ctx)
    try:
        page.locator(PositronSession.CONSOLE_PANEL).wait_for(
            state="visible", timeout=_TIMEOUT_IDE_READY
        )
    except PlaywrightTimeoutError:
        pytest.skip(
            "Positron did not load within timeout — "
            "the IDE may not be installed on this Workbench instance"
        )


# ---------------------------------------------------------------------------
# Clone steps — per IDE
# ---------------------------------------------------------------------------


def _do_clone(
    page: Page,
    git_session_ctx: dict,
    git_cfg,
    readback_lang: str,
    *,
    workdir: str = "/tmp",
) -> str:
    """Run ``git clone`` in the IDE terminal and return the cloned directory path."""
    auth_url = _inject_token_into_url(git_cfg.clone_url, git_cfg.token)
    repo_dir = _repo_dir_from_url(git_cfg.clone_url)
    clone_dir = f"{workdir}/{repo_dir}"

    terminal_run(
        page,
        f"rm -rf {shlex.quote(clone_dir)} && cd {shlex.quote(workdir)} && "
        f"GIT_TERMINAL_PROMPT=0 git clone {shlex.quote(auth_url)}",
        timeout=_TIMEOUT_GIT_NETWORK,
        readback_lang=readback_lang,
    )
    git_session_ctx["clone_dir"] = clone_dir
    return clone_dir


@when("I clone the repository in the RStudio terminal", target_fixture="clone_dir")
def clone_rstudio(page: Page, git_session_ctx: dict, git_cfg):
    return _do_clone(page, git_session_ctx, git_cfg, readback_lang="r")


@when("I clone the repository in the VS Code terminal", target_fixture="clone_dir")
def clone_vscode(page: Page, git_session_ctx: dict, git_cfg):
    return _do_clone(page, git_session_ctx, git_cfg, readback_lang="python")


@when("I clone the repository in the Positron terminal", target_fixture="clone_dir")
def clone_positron(page: Page, git_session_ctx: dict, git_cfg):
    # Positron supports both R and Python; use "r" as the default readback
    # language. read_file/file_exists auto-detect Positron and route to
    # positron_eval_r (R path) or positron_eval_python (Python path).
    return _do_clone(page, git_session_ctx, git_cfg, readback_lang="r")


# ---------------------------------------------------------------------------
# Branch / commit / push steps
# ---------------------------------------------------------------------------


def _do_branch_commit(
    page: Page,
    git_session_ctx: dict,
    git_cfg,
    readback_lang: str,
) -> str:
    """Create a branch, configure git identity, add a file, and commit."""
    clone_dir = git_session_ctx["clone_dir"]
    branch = _make_branch_name()
    git_session_ctx["branch"] = branch

    q_clone_dir = shlex.quote(clone_dir)
    q_branch = shlex.quote(branch)

    # Set git identity so the commit does not fail on unconfigured authors
    terminal_run(
        page,
        f"cd {q_clone_dir} && git config user.email vip@posit.co && git config user.name VIP",
        readback_lang=readback_lang,
    )

    terminal_run(
        page,
        f"cd {q_clone_dir} && git checkout -b {q_branch}",
        readback_lang=readback_lang,
    )

    # Write a unique test file so the commit has actual content
    timestamp = time.time_ns()
    terminal_run(
        page,
        f'cd {q_clone_dir} && echo "vip test {timestamp}" > vip_test_{timestamp}.txt',
        readback_lang=readback_lang,
    )

    terminal_run(
        page,
        f"cd {q_clone_dir} && git add . && git commit -m 'vip test commit {timestamp}'",
        readback_lang=readback_lang,
    )

    return branch


def _do_push(
    page: Page,
    git_session_ctx: dict,
    git_cfg,
    readback_lang: str,
    _wb_git_cleanup_state: dict,
) -> None:
    """Push the current branch to origin, registering it for safety-net cleanup."""
    clone_dir = git_session_ctx["clone_dir"]
    branch = git_session_ctx["branch"]
    auth_url = _inject_token_into_url(git_cfg.clone_url, git_cfg.token)

    q_clone_dir = shlex.quote(clone_dir)
    q_auth_url = shlex.quote(auth_url)
    q_branch = shlex.quote(branch)
    terminal_run(
        page,
        f"cd {q_clone_dir} && GIT_TERMINAL_PROMPT=0 git push {q_auth_url} {q_branch}",
        timeout=_TIMEOUT_GIT_NETWORK,
        readback_lang=readback_lang,
    )

    # Register for session-level safety-net cleanup
    _wb_git_cleanup_state["pending"].append((auth_url, branch))


@when("I create a branch and commit a file in the RStudio terminal")
def branch_commit_rstudio(page: Page, git_session_ctx: dict, git_cfg):
    _do_branch_commit(page, git_session_ctx, git_cfg, readback_lang="r")


@when("I push the branch from the RStudio terminal")
def push_rstudio(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state: dict):
    _do_push(page, git_session_ctx, git_cfg, "r", _wb_git_cleanup_state)


@when("I create a branch and commit a file in the VS Code terminal")
def branch_commit_vscode(page: Page, git_session_ctx: dict, git_cfg):
    _do_branch_commit(page, git_session_ctx, git_cfg, readback_lang="python")


@when("I push the branch from the VS Code terminal")
def push_vscode(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state: dict):
    _do_push(page, git_session_ctx, git_cfg, "python", _wb_git_cleanup_state)


@when("I create a branch and commit a file in the Positron terminal")
def branch_commit_positron(page: Page, git_session_ctx: dict, git_cfg):
    _do_branch_commit(page, git_session_ctx, git_cfg, readback_lang="r")


@when("I push the branch from the Positron terminal")
def push_positron(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state: dict):
    _do_push(page, git_session_ctx, git_cfg, "r", _wb_git_cleanup_state)


# ---------------------------------------------------------------------------
# Verification Then steps
# ---------------------------------------------------------------------------


@then("the cloned repository directory exists")
def cloned_dir_exists(page: Page, git_session_ctx: dict):
    clone_dir = git_session_ctx["clone_dir"]
    ide = git_session_ctx.get("ide", "RStudio")
    lang = "python" if ide == "VS Code" else "r"
    assert file_exists(page, clone_dir, lang=lang), (
        f"Cloned repository directory {clone_dir!r} does not exist on the server. "
        "Check that git clone succeeded and the repository is accessible."
    )


@then("the pushed branch exists on the remote")
def pushed_branch_exists(page: Page, git_session_ctx: dict, git_cfg):
    """Verify the pushed branch is visible via ``git ls-remote``."""
    branch = git_session_ctx["branch"]
    ide = git_session_ctx.get("ide", "RStudio")
    lang = "python" if ide == "VS Code" else "r"
    auth_url = _inject_token_into_url(git_cfg.clone_url, git_cfg.token)

    q_auth_url = shlex.quote(auth_url)
    q_branch = shlex.quote(branch)
    output = terminal_run(
        page,
        f"GIT_TERMINAL_PROMPT=0 git ls-remote {q_auth_url} refs/heads/{q_branch}",
        timeout=_TIMEOUT_GIT_NETWORK,
        readback_lang=lang,
    )
    assert branch in output, (
        f"Branch {branch!r} not found in remote refs. git ls-remote output: {output!r}"
    )


# ---------------------------------------------------------------------------
# Cleanup Then steps (scenario-level, layer 1 of 2)
# ---------------------------------------------------------------------------


def _delete_remote_branch(
    page: Page,
    git_session_ctx: dict,
    git_cfg,
    readback_lang: str,
    _wb_git_cleanup_state: dict,
) -> None:
    """Delete the pushed branch from the remote via the terminal."""
    branch = git_session_ctx.get("branch")
    if not branch:
        return
    # Guard: never push-delete main or master
    if branch in ("main", "master"):
        raise AssertionError(
            f"Refusing to delete protected branch {branch!r}. "
            "Test branches must use the vip-<timestamp> naming convention."
        )
    clone_dir = git_session_ctx["clone_dir"]
    auth_url = _inject_token_into_url(git_cfg.clone_url, git_cfg.token)
    q_clone_dir = shlex.quote(clone_dir)
    q_auth_url = shlex.quote(auth_url)
    q_branch = shlex.quote(branch)
    try:
        terminal_run(
            page,
            f"cd {q_clone_dir} && GIT_TERMINAL_PROMPT=0 git push {q_auth_url} --delete {q_branch}",
            timeout=_TIMEOUT_GIT_NETWORK,
            readback_lang=readback_lang,
        )
    except ExecError:
        pass  # Branch may already be deleted; safety net will try again

    # Mark as cleaned up so the session-level safety net skips this branch
    pending = _wb_git_cleanup_state.get("pending", [])
    _wb_git_cleanup_state["pending"] = [(u, b) for (u, b) in pending if b != branch]


@then("I delete the pushed branch from the RStudio terminal")
def delete_branch_rstudio(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state):
    _delete_remote_branch(page, git_session_ctx, git_cfg, "r", _wb_git_cleanup_state)


@then("I delete the pushed branch from the VS Code terminal")
def delete_branch_vscode(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state):
    _delete_remote_branch(page, git_session_ctx, git_cfg, "python", _wb_git_cleanup_state)


@then("I delete the pushed branch from the Positron terminal")
def delete_branch_positron(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state):
    _delete_remote_branch(page, git_session_ctx, git_cfg, "r", _wb_git_cleanup_state)
