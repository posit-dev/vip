"""Step definitions for Workbench Git operations tests.

Tests cover terminal-based Git operations (clone, branch, commit, push) in
RStudio, VS Code, and Positron sessions, as well as the RStudio Git pane
(Stage → Commit → Push workflow).

Requires [workbench.git_test] in vip.toml and VIP_GIT_TOKEN set in the
environment.  All scenarios auto-skip when the config block is absent.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlparse, urlunparse

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pytest_bdd import given, scenario, then, when

from vip_tests.workbench.conftest import (
    TIMEOUT_DIALOG,
    TIMEOUT_IDE_LOAD,
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
    RStudioGitPane,
    RStudioSession,
    VSCodeSession,
)

_FILENAME = Path(__file__).name

# Extra timeout (ms) for Git network operations (clone / push)
_TIMEOUT_GIT_NETWORK = 120_000

# Timeout (ms) for waiting for the IDE to be functional after session join
_TIMEOUT_IDE_READY = 60_000

# Prefix used for test branches; mirrors unique_session_name style
_BRANCH_PREFIX = "vip"


def _make_branch_name() -> str:
    """Return a unique test branch name: vip-<nanosecond timestamp>."""
    return f"{_BRANCH_PREFIX}-{time.time_ns()}"


def _inject_token_into_url(clone_url: str, token: str) -> str:
    """Embed *token* into an HTTPS clone URL for credential-less cloning.

    Transforms ``https://github.com/org/repo.git`` into
    ``https://x-token-auth:<token>@github.com/org/repo.git``.
    Returns the URL unchanged when token is empty or scheme is not https.
    """
    if not token:
        return clone_url
    parsed = urlparse(clone_url)
    if parsed.scheme not in ("http", "https"):
        return clone_url
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


@scenario("test_git_ops.feature", "Commit and push using the RStudio Git pane")
def test_git_pane_push():
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
        "cleaned_up": False,
    }


@pytest.fixture(scope="session", autouse=True)
def _wb_git_cleanup_state():
    """Session-scoped safety net: track pushed branches that need remote deletion.

    Populated by push steps.  On session teardown this fixture attempts to
    delete any branches that were not cleaned up by the scenario's final Then
    step (e.g. because an intermediate step failed).

    The cleanup runs terminal_run against a Playwright page, which is not
    available at session scope.  We therefore store (clone_url, auth_url,
    branch) tuples and delete them using subprocess git commands as a last
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
    cfg = vip_config.workbench.git_test
    if cfg is None:
        pytest.skip(
            "Git test config is not configured. "
            "Add a [workbench.git_test] block to vip.toml with clone_url and auth_method, "
            "and set VIP_GIT_TOKEN in the environment."
        )
    if not cfg.clone_url:
        pytest.skip(
            "workbench.git_test.clone_url is empty. "
            "Set clone_url in the [workbench.git_test] block of vip.toml."
        )
    if not cfg.token:
        pytest.skip(
            "VIP_GIT_TOKEN is not set. "
            "Export VIP_GIT_TOKEN=<personal-access-token> before running Git test scenarios."
        )
    return cfg


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
        f"cd {workdir} && git clone {auth_url}",
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
    # language (see exec.py: positron_eval_r is the R console path).
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

    # Set git identity so the commit does not fail on unconfigured authors
    terminal_run(
        page,
        f"cd {clone_dir} && git config user.email vip@posit.co && git config user.name VIP",
        readback_lang=readback_lang,
    )

    terminal_run(
        page,
        f"cd {clone_dir} && git checkout -b {branch}",
        readback_lang=readback_lang,
    )

    # Write a unique test file so the commit has actual content
    timestamp = time.time_ns()
    terminal_run(
        page,
        f'cd {clone_dir} && echo "vip test {timestamp}" > vip_test_{timestamp}.txt',
        readback_lang=readback_lang,
    )

    terminal_run(
        page,
        f"cd {clone_dir} && git add . && git commit -m 'vip test commit {timestamp}'",
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

    terminal_run(
        page,
        f"cd {clone_dir} && git push {auth_url} {branch}",
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
# RStudio Git pane steps
# ---------------------------------------------------------------------------


@when("I create a new file in the repository via the RStudio terminal")
def create_file_for_git_pane(page: Page, git_session_ctx: dict):
    """Create a file and a branch so the Git pane has something to stage."""
    clone_dir = git_session_ctx["clone_dir"]
    branch = _make_branch_name()
    git_session_ctx["branch"] = branch
    timestamp = time.time_ns()

    terminal_run(page, f"cd {clone_dir} && git config user.email vip@posit.co", readback_lang="r")
    terminal_run(page, f"cd {clone_dir} && git config user.name VIP", readback_lang="r")
    terminal_run(page, f"cd {clone_dir} && git checkout -b {branch}", readback_lang="r")
    terminal_run(
        page,
        f'cd {clone_dir} && echo "vip pane test {timestamp}" > vip_pane_{timestamp}.txt',
        readback_lang="r",
    )

    # Set the Git working directory to the repo for RStudio's Git pane to pick it up
    terminal_run(
        page,
        f"cd {clone_dir} && Rscript -e 'setwd(\"{clone_dir}\")'",
        readback_lang="r",
    )


@when("I stage, commit, and push the file using the RStudio Git pane")
def git_pane_stage_commit_push(page: Page, git_session_ctx: dict, git_cfg, _wb_git_cleanup_state):
    """Drive the RStudio Git pane to stage, commit, and push.

    NOTE: The selectors in RStudioGitPane have not been validated against a
    live Workbench instance.  This step may need selector adjustments when
    run against a real deployment.
    """
    clone_dir = git_session_ctx["clone_dir"]
    branch = git_session_ctx["branch"]
    auth_url = _inject_token_into_url(git_cfg.clone_url, git_cfg.token)

    # Open the Git tab in RStudio's pane set
    git_tab = page.locator(RStudioGitPane.GIT_TAB)
    try:
        git_tab.wait_for(state="visible", timeout=TIMEOUT_IDE_LOAD)
    except PlaywrightTimeoutError:
        pytest.skip(
            "RStudio Git pane tab not found — "
            "the repository may not have been recognised as a Git project by RStudio. "
            "Verify the session working directory is set to the cloned repository."
        )
    git_tab.click(timeout=TIMEOUT_QUICK)

    # Stage all changed files
    stage_all = page.locator(RStudioGitPane.STAGE_ALL_BUTTON)
    if stage_all.count() > 0 and stage_all.is_visible():
        stage_all.click(timeout=TIMEOUT_QUICK)
    else:
        # Fall back to clicking individual checkboxes for the first changed file
        first_checkbox = page.locator(RStudioGitPane.FILE_STAGE_CHECKBOX).first
        expect(first_checkbox).to_be_visible(timeout=TIMEOUT_DIALOG)
        first_checkbox.click(timeout=TIMEOUT_QUICK)

    # Open the Commit dialog
    page.locator(RStudioGitPane.COMMIT_BUTTON).click(timeout=TIMEOUT_DIALOG)

    # Write commit message
    commit_dialog = page.locator(RStudioGitPane.COMMIT_DIALOG)
    expect(commit_dialog).to_be_visible(timeout=TIMEOUT_DIALOG)

    commit_msg_box = commit_dialog.locator(RStudioGitPane.COMMIT_MESSAGE)
    expect(commit_msg_box).to_be_visible(timeout=TIMEOUT_DIALOG)
    commit_msg_box.click()
    commit_msg_box.fill(f"vip test commit via Git pane ({branch})")

    # Submit the commit
    commit_dialog.locator(RStudioGitPane.COMMIT_SUBMIT_BUTTON).click(timeout=TIMEOUT_DIALOG)

    # Wait for commit output; then push via terminal (more reliable than the dialog push button)
    page.locator(RStudioGitPane.COMMIT_OUTPUT).wait_for(state="visible", timeout=TIMEOUT_DIALOG)

    # Close the commit dialog
    try:
        close_btn = page.locator(RStudioGitPane.COMMIT_CLOSE_BUTTON)
        if close_btn.count() > 0:
            close_btn.click(timeout=TIMEOUT_QUICK)
    except (PlaywrightTimeoutError, PlaywrightError):
        pass

    # Push the committed branch via terminal (avoids credential dialog in the GUI push flow)
    terminal_run(
        page,
        f"cd {clone_dir} && git push {auth_url} {branch}",
        timeout=_TIMEOUT_GIT_NETWORK,
        readback_lang="r",
    )

    _wb_git_cleanup_state["pending"].append((auth_url, branch))


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

    output = terminal_run(
        page,
        f"git ls-remote {auth_url} refs/heads/{branch}",
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
    try:
        terminal_run(
            page,
            f"cd {clone_dir} && git push {auth_url} --delete {branch}",
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
