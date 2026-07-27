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

import base64
import re
import shlex
import time
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
from vip_tests.workbench.exec import ExecError, terminal_run
from vip_tests.workbench.pages import Homepage, NewSessionDialog, VSCodeSession

pytestmark = pytest.mark.order(60)

_FILENAME = Path(__file__).name

# Timeout for the combined setup+deploy command. With uv the venv+install take
# ~1s and --no-verify skips rsconnect's multi-minute boot wait, so the whole
# command finishes well under a minute; the ceiling is bounded so a hang cannot
# consume the 5-minute suite budget.
_DEPLOY_TIMEOUT_MS = 120_000

# Timeout for the short cleanup commands (rm -rf).
_VENV_QUICK_TIMEOUT_MS = 30_000

# Post-deploy reachability polling (deploy runs --no-verify, so the Shiny
# process may still be booting when the deploy command returns).
_REACHABILITY_TIMEOUT_S = 60
_REACHABILITY_POLL_S = 3


def _log(message: str) -> None:
    """Emit a timestamped progress line so a long deploy step is not mistaken
    for a hang. Visible under ``pytest -s`` / ``--verbose``."""
    print(f"    [{time.strftime('%H:%M:%S')}] vip-publish: {message}", flush=True)


def _build_deploy_script(
    *,
    bundle_dir: str,
    manifest_path: str,
    venv_dir: str,
    app_r: str,
    manifest_url: str,
    platform: str,
    connect_url: str,
    api_key: str,
    title: str,
) -> str:
    """Return a single shell command that assembles the bundle and deploys it.

    Collapsing setup+deploy into one command is deliberate: every keystroke is
    typed before anything runs, so the venv-activation terminal VS Code spawns
    cannot hijack a later command (the multi-terminal race). The script:

    1. writes ``app.R`` (base64-decoded so content survives the terminal),
    2. downloads the reference manifest (``curl -fsS``; tags VIP_DL_FAIL on
       network failure) and patches its ``platform`` with whatever python is
       available,
    3. provisions ``rsconnect`` — ``uv`` (venv+install in ~1s) when present,
       else ``python -m venv`` + ``pip`` — tagging VIP_NO_PY if no interpreter,
    4. runs ``rsconnect deploy manifest ... --no-verify``.

    Failure tags (VIP_NO_PY / VIP_DL_FAIL) let the caller map environment
    problems to skips while real deploy errors stay failures. Values are
    shlex.quote'd; the title contains spaces (unique_session_name).
    """
    app_r_b64 = base64.b64encode(app_r.encode()).decode("ascii")
    q_bundle = shlex.quote(bundle_dir)
    q_manifest = shlex.quote(manifest_path)
    q_venv = shlex.quote(venv_dir)
    q_url = shlex.quote(manifest_url)
    q_platform = shlex.quote(platform)
    q_server = shlex.quote(connect_url)
    q_key = shlex.quote(api_key)
    q_title = shlex.quote(title)
    # Patch platform with a python one-liner; PYBIN is resolved below. The
    # manifest path and platform are passed as argv (shell-quoted) so Python
    # receives the platform as a string -- interpolating it into the Python
    # source would emit ``m['platform']=4.6.1`` (a SyntaxError), since the
    # version is not a valid Python literal.
    patch = (
        '"$PYBIN" -c '
        "'import json,sys; p=sys.argv[1]; m=json.load(open(p)); "
        'm["platform"]=sys.argv[2]; json.dump(m,open(p,"w"))\' '
        f"{q_manifest} {q_platform}"
    )
    return (
        f"set -e; "
        f"mkdir -p {q_bundle}; "
        f"printf %s {app_r_b64} | base64 -d > {q_bundle}/app.R; "
        # Resolve a python interpreter for the manifest patch (uv provides one too).
        f'PYBIN="$(command -v python3 || command -v python || true)"; '
        # Download the manifest (network/firewall -> VIP_DL_FAIL).
        f"curl -fsS -o {q_manifest} {q_url} || {{ echo VIP_DL_FAIL; exit 21; }}; "
        # Patch platform if we have a python; harmless to skip if not.
        f'if [ -n "$PYBIN" ]; then {patch}; fi; '
        # Provision rsconnect: prefer uv (fast), else python venv + pip.
        f"if command -v uv >/dev/null 2>&1; then "
        f"  uv venv {q_venv} >/dev/null && "
        f"  uv pip install --python {q_venv}/bin/python --quiet rsconnect-python >/dev/null; "
        f'elif [ -n "$PYBIN" ]; then '
        f'  "$PYBIN" -m venv {q_venv} && '
        f"  {q_venv}/bin/pip install --quiet --upgrade rsconnect-python; "
        f"else echo VIP_NO_PY; exit 22; fi; "
        # Deploy (--no-verify: skip rsconnect's multi-minute boot probe).
        f"{q_venv}/bin/rsconnect deploy manifest {q_manifest} "
        f"--server {q_server} --api-key {q_key} --title {q_title} --no-verify"
    )


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

    ``rsconnect-python`` is not assumed to be on PATH: the whole setup+deploy
    runs as a single shell command (see ``_build_deploy_script``) that
    provisions a throwaway venv -- preferring ``uv`` (venv + install in ~1s),
    falling back to ``python -m venv`` + ``pip`` -- deploys with that venv's
    ``rsconnect``, and the venv and bundle are torn down afterwards.  When no
    interpreter is available the script tags ``VIP_NO_PY`` and the step skips.
    """
    # Open the integrated terminal. Filter to the visible input: a VS Code
    # session can end up with more than one terminal (e.g. the Python extension
    # spawns one to activate a venv), and a bare ``.xterm-helper-textarea``
    # locator then trips Playwright's strict mode. terminal_run re-ensures the
    # terminal itself, so this just confirms an input is present.
    page.keyboard.press("Control+`")
    terminal_input = page.locator(f"{VSCodeSession.TERMINAL_INPUT}:visible").last
    expect(terminal_input).to_be_visible(timeout=TIMEOUT_SESSION_START)

    title = f"vip_test_shiny_{unique_session_name(_FILENAME)}"
    venv_dir = f"/tmp/vip_rsconnect_venv_{uuid.uuid4().hex}"
    bundle_dir = f"/tmp/vip_shiny_bundle_{uuid.uuid4().hex}"
    manifest_path = f"{bundle_dir}/manifest.json"

    _log("assembling bundle + provisioning rsconnect (single command)")
    try:
        # Run the entire setup+deploy as ONE shell command. Doing it in a single
        # terminal_run (rather than ~6) is what makes this reliable: every
        # keystroke is typed before any command runs, so the venv-activation
        # terminal that VS Code's Python extension spawns cannot steal a later
        # command (the multi-terminal race that hung earlier). It is also far
        # faster -- uv creates the venv and installs rsconnect in ~1s vs ~40s for
        # python -m venv + pip -- and keeps output short so the Monaco-editor
        # readback never has to scroll past a virtualized long log.
        setup_script = _build_deploy_script(
            bundle_dir=bundle_dir,
            manifest_path=manifest_path,
            venv_dir=venv_dir,
            app_r=shiny_bundle_spec["app_r"],
            manifest_url=shiny_bundle_spec["manifest_url"],
            platform=shiny_bundle_spec["platform"],
            connect_url=connect_url,
            api_key=vip_config.connect.api_key,
            title=title,
        )
        try:
            output = terminal_run(
                page,
                setup_script,
                timeout=_DEPLOY_TIMEOUT_MS,
                readback_lang="python",
            )
        except ExecError as exc:
            # The combined script tags its own failure modes so we can map an
            # environment problem (no python/uv, unreachable repo) to a skip
            # while a genuine rsconnect failure stays a hard failure.
            msg = str(exc)
            if "VIP_NO_PY" in msg:
                pytest.skip("Neither uv nor python3/python is available in the Workbench session")
            if "VIP_DL_FAIL" in msg:
                pytest.skip(
                    f"Could not download the Shiny manifest from "
                    f"{shiny_bundle_spec['manifest_url']} (network/firewall constraint)"
                )
            raise
        _log("deploy command returned")
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

    # Primary: parse the GUID from rsconnect's success output. rsconnect sets
    # the Connect content *name* to a slug derived from the bundle, not our
    # --title, so a name lookup does not find it; the deploy output is the
    # authoritative source. It prints both a dashboard URL (/connect/#/apps/GUID)
    # and a direct URL (/content/GUID/), so match either path form.
    m = re.search(r"/(?:apps|content)/([0-9a-f-]{36})", output)
    if m:
        guid = m.group(1)
        content_url = f"{connect_url.rstrip('/')}/content/{guid}/"
    else:
        # Fallback: title lookup (older Connect set name == title on some paths).
        content = connect_client._find_content_by_name(title)
        guid = content["guid"] if content else None
        content_url = content.get("content_url", "") if content else ""

    if guid:
        _log(f"deployed content guid={guid}")
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
    """Verify the deployed content serves a live page via the Connect API.

    Deploy runs with ``--no-verify``, so the Shiny process may still be booting.
    Using the Connect API key, poll the content URL with a bounded budget until
    it returns a live page (HTTP < 400 whose body carries the app's "VIP test"
    marker), rather than assuming it is up the instant the deploy returns.
    """
    guid = publish_context.get("content_guid")
    assert guid, "No content GUID was recorded by the deploy step"

    content = connect_client.get_content(guid)
    url = publish_context.get("content_url") or content.get("content_url", "")
    if not url:
        return

    _log(f"verifying live app via Connect API at {url}")
    deadline = time.monotonic() + _REACHABILITY_TIMEOUT_S
    last_status = None
    while time.monotonic() < deadline:
        try:
            resp = connect_client.fetch_content(url)
            last_status = resp.status_code
            # A booted Shiny app returns its HTML shell containing the UI text.
            if resp.status_code < 400 and "vip test" in resp.text.lower():
                _log(f"live app confirmed (HTTP {resp.status_code}, 'VIP test' rendered)")
                return
            # Page reachable but content not yet rendered — keep polling.
            if resp.status_code < 400:
                last_status = f"{resp.status_code} (marker not yet present)"
        except Exception as exc:  # transient during first-boot
            last_status = repr(exc)
        time.sleep(_REACHABILITY_POLL_S)

    raise AssertionError(
        f"Deployed content at {url!r} was not confirmed live within "
        f"{_REACHABILITY_TIMEOUT_S}s (last result: {last_status})"
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

    _log(f"removing deployed content guid={guid}")
    removed = connect_client._delete_content_verified(guid)
    assert removed, f"Deployed content {guid} was not removed from Connect"
    _log("deployed content removed")
