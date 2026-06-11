"""Step definitions for Workbench → Connect publish tests.

These cross-product tests verify that a user can deploy content from a
Workbench session to Connect using the terminal (rsconnect-python CLI) and,
when the IDE extension installation primitive lands, via the Posit Publisher
extension UI.

Both scenarios require ``@workbench`` and ``@connect`` products to be
configured.  The plugin's ``_should_deselect_for_product`` logic silently
excludes the tests when either product is absent.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
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
from vip_tests.workbench.exec import terminal_run
from vip_tests.workbench.pages import Homepage, NewSessionDialog, VSCodeSession

_FILENAME = Path(__file__).name

# Timeout for rsconnect deploy, which bundles, uploads, and deploys.
_DEPLOY_TIMEOUT_MS = 180_000


@scenario(
    "test_publish_to_connect.feature",
    "User deploys a Python Shiny app from a Workbench terminal",
)
def test_deploy_python_shiny_via_terminal():
    pass


@scenario(
    "test_publish_to_connect.feature",
    "User deploys via Posit Publisher extension",
)
def test_publish_via_publisher():
    pytest.skip(
        reason=(
            "Posit Publisher extension UI scenario requires an IDE extension installation "
            "primitive that does not yet exist. Tracked as a follow-up capability gap."
        )
    )


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@pytest.fixture
def publish_context():
    """Holds mutable state across steps within one scenario."""
    return {"session_name": None, "content_guid": None, "content_url": None}


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


@given("the user is logged in to Workbench")
def user_logged_in(
    page: Page,
    workbench_url: str,
    test_username: str,
    test_password: str,
    auth_provider: str,
    interactive_auth: bool,
    auth_mode: str,
    workbench_auth_error: str | None,
):
    """Log in to Workbench and verify homepage loads."""
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


@given("the user opens a VS Code session")
def open_vscode_session(page: Page, publish_context: dict):
    """Start a VS Code session and wait for it to reach Active state."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    session_name = unique_session_name(_FILENAME)
    publish_context["session_name"] = session_name

    page.locator(Homepage.NEW_SESSION_BUTTON).first.click(timeout=TIMEOUT_DIALOG)

    dialog = page.locator(NewSessionDialog.DIALOG)
    expect(dialog.locator(NewSessionDialog.TITLE)).to_have_text(
        "New Session", timeout=TIMEOUT_DIALOG
    )

    ide_display = NewSessionDialog.ide_display_name("VS Code")
    ide_tab = dialog.get_by_role("tab", name=ide_display)
    if ide_tab.count() == 0:
        try:
            cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
            if cancel.count() > 0:
                cancel.click(timeout=TIMEOUT_QUICK)
        except (PlaywrightTimeoutError, PlaywrightError):
            pass
        pytest.skip("VS Code IDE not available in this Workbench deployment")

    ide_tab.click(timeout=TIMEOUT_QUICK)

    launch_btn = page.locator(NewSessionDialog.LAUNCH_BUTTON)
    try:
        launch_btn.wait_for(state="visible", timeout=TIMEOUT_QUICK)
    except PlaywrightTimeoutError:
        try:
            cancel = page.locator(NewSessionDialog.CANCEL_BUTTON)
            if cancel.count() > 0:
                cancel.click(timeout=TIMEOUT_QUICK)
        except (PlaywrightTimeoutError, PlaywrightError):
            pass
        pytest.skip(
            "VS Code tab opened but Launch button did not appear — "
            "the IDE may not be installed or fully available on this Workbench instance"
        )

    page.fill(NewSessionDialog.SESSION_NAME, session_name)

    checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
    if checkbox.is_checked():
        checkbox.click()
    expect(checkbox).not_to_be_checked(timeout=TIMEOUT_QUICK)

    launch_btn.click(timeout=TIMEOUT_QUICK)

    # Wait for Active, then navigate into the session.
    session_row = wait_for_session_active(page, session_name)
    session_link = session_row.locator(f"a[title='join {session_name}']")
    expect(session_link).to_be_visible(timeout=TIMEOUT_DIALOG)
    session_link.click()

    # Wait for VS Code to load.
    try:
        page.locator(VSCodeSession.WORKBENCH).wait_for(state="visible", timeout=TIMEOUT_IDE_LOAD)
    except Exception:
        pytest.skip(
            "VS Code did not load within timeout — "
            "the IDE may not be installed on this Workbench instance"
        )


@when("the user deploys the Python Shiny app via the terminal")
def deploy_python_shiny_via_terminal(
    page: Page,
    publish_context: dict,
    python_shiny_bundle_path: Path,
    connect_url: str,
    vip_config,
    connect_client,
    _connect_created_guids: list,
):
    """Run ``rsconnect deploy shiny`` in the VS Code terminal and register the GUID."""
    # Open the integrated terminal.
    page.keyboard.press("Control+`")
    terminal_input = page.locator(VSCodeSession.TERMINAL_INPUT)
    expect(terminal_input).to_be_visible(timeout=TIMEOUT_SESSION_START)

    title = f"vip_test_shiny_{unique_session_name(_FILENAME)}"

    output = terminal_run(
        page,
        (
            f"rsconnect deploy shiny {python_shiny_bundle_path} "
            f"--server {connect_url} "
            f"--api-key {vip_config.connect.api_key} "
            f"--title {title}"
        ),
        timeout=_DEPLOY_TIMEOUT_MS,
        readback_lang="python",
    )

    # Primary: stable API title lookup (version-independent).
    content = connect_client._find_content_by_name(title)
    if content:
        guid = content["guid"]
        content_url = content.get("content_url", "")
    else:
        # Fallback: parse the rsconnect output URL.
        m = re.search(r"/apps/([0-9a-f-]{36})", output)
        guid = m.group(1) if m else None
        content_url = ""

    if guid:
        _connect_created_guids.append(guid)
        publish_context["content_guid"] = guid
        publish_context["content_url"] = content_url
    else:
        warnings.warn(
            f"Could not determine GUID for deployed content '{title}'; "
            "relying on end-of-run tag sweep for cleanup.",
            stacklevel=2,
        )

    assert guid, (
        f"rsconnect deploy did not produce a discoverable content item (title={title!r}). "
        f"Terminal output:\n{output}"
    )


@when("the user deploys via the Posit Publisher extension UI")
def deploy_via_publisher_ui(page: Page):
    """Placeholder — blocked until IDE extension installation primitive exists."""
    pytest.skip(
        "Posit Publisher extension UI scenario requires an IDE extension installation "
        "primitive that does not yet exist. Tracked as a follow-up capability gap."
    )


@then("the app is reachable on Connect")
def app_reachable_on_connect(publish_context: dict, connect_client):
    """Verify the deployed content is accessible via HTTP."""
    guid = publish_context.get("content_guid")
    assert guid, "No content GUID was recorded by the deploy step"

    content = connect_client.get_content(guid)
    url = publish_context.get("content_url") or content.get("content_url", "")
    if url:
        resp = connect_client.fetch_content(url)
        assert resp.status_code < 400, (
            f"Deployed content at {url!r} returned HTTP {resp.status_code}"
        )
