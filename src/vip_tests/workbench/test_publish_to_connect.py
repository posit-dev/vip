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
import shlex
import uuid
import warnings
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from pytest_bdd import given, scenario, then, when

from vip.clients.connect import _VIP_CONTENT_TAG
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
from vip_tests.workbench.exec import ExecError, terminal_run, write_bundle
from vip_tests.workbench.pages import Homepage, NewSessionDialog, VSCodeSession

pytestmark = pytest.mark.order(60)

_FILENAME = Path(__file__).name

# Timeout for rsconnect deploy, which bundles, uploads, and deploys.
_DEPLOY_TIMEOUT_MS = 180_000

# Timeout for the short venv-management commands (create, pip install, cleanup).
_VENV_SETUP_TIMEOUT_MS = 120_000
_VENV_QUICK_TIMEOUT_MS = 30_000


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
    shiny_bundle_spec: dict,
    connect_url: str,
    vip_config,
    connect_client,
    _connect_created_guids: list,
):
    """Run ``rsconnect deploy manifest`` in the VS Code terminal and register the GUID.

    Deploys the *same* Shiny bundle as the Connect deploy test: the minimal R
    ``app.R`` plus the reference ``shiny_manifest.json``.  ``deploy manifest`` --
    unlike ``deploy shiny``, which is Python-only -- deploys any content type
    from a prepared manifest and builds it server-side, so the session needs no
    local R.

    The bundle is assembled inside the Workbench session's own filesystem so
    ``rsconnect`` finds it locally no matter where pytest runs: the tiny
    ``app.R`` is typed via the terminal, while the ~80 KB ``manifest.json`` (the
    full package closure -- far too large to type reliably) is downloaded from
    the public repo with ``curl`` and its ``platform`` patched to the server's R.
    A download blocked by a firewall skips (an environment constraint, not a
    publishing defect).

    ``rsconnect-python`` is not assumed to be on PATH: we create a throwaway
    venv from whatever ``python3`` the session provides, install
    ``rsconnect-python`` into it, deploy with that venv's ``rsconnect``, and tear
    the venv and bundle down afterwards.  A missing ``python3`` skips.
    """
    # Open the integrated terminal. Filter to the visible input: a VS Code
    # session can end up with more than one terminal (e.g. the Python extension
    # spawns one to activate a venv), and a bare ``.xterm-helper-textarea``
    # locator then trips Playwright's strict mode. terminal_run re-ensures the
    # terminal itself, so this just confirms an input is present.
    page.keyboard.press("Control+`")
    terminal_input = page.locator(f"{VSCodeSession.TERMINAL_INPUT}:visible").last
    expect(terminal_input).to_be_visible(timeout=TIMEOUT_SESSION_START)

    # Preflight: a Python interpreter must be on PATH to build the venv.
    # Prefer ``python3`` but accept ``python`` so sessions without the
    # ``python3`` symlink still qualify. Absence of Python is an environment
    # precondition, not a publishing defect, so skip rather than fail here --
    # only a genuine deploy failure below should FAIL the check.
    try:
        python_bin = terminal_run(
            page,
            "command -v python3 || command -v python",
            timeout=_VENV_QUICK_TIMEOUT_MS,
            readback_lang="python",
        ).strip()
    except ExecError:
        pytest.skip(
            "Neither python3 nor python is on PATH in the Workbench session; "
            "cannot create a venv to install rsconnect-python for deployment."
        )

    # A blank result means the readback captured no interpreter path (e.g. the
    # command's stdout escaped the redirect). Skip rather than build an empty
    # ``python_bin`` that would run as ``'' -m venv`` (exit 127, "-m: command
    # not found").
    if not python_bin:
        pytest.skip(
            "Could not resolve a python3/python interpreter path in the Workbench "
            "session; the preflight returned no output, so a venv for "
            "rsconnect-python cannot be created."
        )

    title = f"vip_test_shiny_{unique_session_name(_FILENAME)}"
    venv_dir = f"/tmp/vip_rsconnect_venv_{uuid.uuid4().hex}"
    bundle_dir = f"/tmp/vip_shiny_bundle_{uuid.uuid4().hex}"
    rsconnect_bin = f"{venv_dir}/bin/rsconnect"

    manifest_path = f"{bundle_dir}/manifest.json"
    try:
        # Assemble the bundle in the session's own filesystem so rsconnect finds
        # it locally (the pytest host's /tmp is not visible here). app.R is tiny
        # and typed directly; the ~80 KB manifest is fetched over HTTPS.
        write_bundle(
            page,
            bundle_dir,
            {"app.R": shiny_bundle_spec["app_r"]},
            timeout=_VENV_QUICK_TIMEOUT_MS,
            readback_lang="python",
        )

        # Download the reference manifest into the session. A firewalled session
        # cannot reach the public repo -- treat that as an environment skip, not
        # a deploy failure. curl -fsS makes HTTP errors non-zero so ExecError
        # fires instead of silently writing an error page.
        manifest_url = shiny_bundle_spec["manifest_url"]
        try:
            terminal_run(
                page,
                f"curl -fsS -o {manifest_path} {manifest_url}",
                timeout=_VENV_QUICK_TIMEOUT_MS,
                readback_lang="python",
            )
        except ExecError as exc:
            pytest.skip(
                f"Could not download the Shiny manifest from {manifest_url} in the "
                f"Workbench session (network/firewall constraint): {exc}"
            )

        # Patch the manifest platform to the server's newest R, matching what the
        # Connect deploy test does, so both suites deploy an identical bundle.
        platform = shiny_bundle_spec["platform"]
        terminal_run(
            page,
            (
                f"{python_bin} -c "
                f""""import json; p='{manifest_path}'; """
                f"m=json.load(open(p)); m['platform']='{platform}'; "
                f'''json.dump(m,open(p,'w'))"'''
            ),
            timeout=_VENV_QUICK_TIMEOUT_MS,
            readback_lang="python",
        )

        # Create the venv and install rsconnect-python into it.
        terminal_run(
            page,
            f"{python_bin} -m venv {venv_dir}",
            timeout=_VENV_SETUP_TIMEOUT_MS,
            readback_lang="python",
        )
        terminal_run(
            page,
            f"{venv_dir}/bin/pip install --quiet --upgrade rsconnect-python",
            timeout=_VENV_SETUP_TIMEOUT_MS,
            readback_lang="python",
        )

        # shlex.quote every interpolated value: the title contains spaces
        # (unique_session_name → "VIP <file> - <worker>-<ns>"), which the shell
        # would otherwise split into extra args ("Got unexpected extra
        # arguments"); the api-key and URL are quoted defensively too.
        output = terminal_run(
            page,
            (
                f"{rsconnect_bin} deploy manifest {shlex.quote(manifest_path)} "
                f"--server {shlex.quote(connect_url)} "
                f"--api-key {shlex.quote(vip_config.connect.api_key)} "
                f"--title {shlex.quote(title)}"
            ),
            timeout=_DEPLOY_TIMEOUT_MS,
            readback_lang="python",
        )
    finally:
        # Tear down the throwaway venv and bundle regardless of deploy outcome.
        for path, label in ((venv_dir, "venv"), (bundle_dir, "bundle")):
            try:
                terminal_run(
                    page,
                    f"rm -rf {path}",
                    timeout=_VENV_QUICK_TIMEOUT_MS,
                    readback_lang="python",
                )
            except ExecError:
                warnings.warn(
                    f"Failed to remove temporary {label} at {path}; "
                    "manual cleanup may be required.",
                    stacklevel=2,
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
        # rsconnect deploy does not go through connect_client.create_content, so
        # the content is not auto-tagged. Tag it with _vip_test explicitly so
        # `vip cleanup` (and the end-of-run sweep) can find and remove it even if
        # this test's own teardown below is skipped or fails. Best-effort.
        connect_client._tag_content(guid, _VIP_CONTENT_TAG)
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


@then("the deployed app is removed from Connect")
def deployed_app_removed_from_connect(publish_context: dict, connect_client):
    """Delete the deployed content and verify it is gone.

    This test creates the content, so cleaning it up is part of the scenario --
    the run must not leave the app behind. The item is also _vip_test-tagged and
    registered in _connect_created_guids, so `vip cleanup` and the end-of-run
    sweep remove it as a backstop if this step is skipped.
    """
    guid = publish_context.get("content_guid")
    assert guid, "No content GUID was recorded by the deploy step"

    removed = connect_client._delete_content_verified(guid)
    assert removed, f"Deployed content {guid} was not removed from Connect"
