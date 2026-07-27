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

# Timeout for the combined setup+deploy command. `--no-verify` skips ONLY
# rsconnect's client-side post-deploy app-boot probe; it does NOT skip the
# server-side deployment task -- rsconnect's emit_task_log()/wait_for_task()
# runs unconditionally and blocks until Connect finishes restoring the manifest's
# full package closure. On a cold Connect package cache that restore compiles the
# ~30-package R closure from source and routinely runs many minutes, so the
# ceiling must be generous (a tight bound would fail a healthy-but-slow build).
# Bounded so a genuine hang still cannot run unbounded; this test is @slow-tagged
# and excluded from `verify --basic`.
_DEPLOY_TIMEOUT_MS = 900_000  # 15 min

# Timeout for the short cleanup commands (rm -rf).
_VENV_QUICK_TIMEOUT_MS = 30_000

# Post-deploy reachability polling. rsconnect exit 0 already means the server-side
# build finished (see above), but deploy runs with --no-verify so the Shiny
# worker process may still be booting when the command returns; poll the content
# URL for a bounded window until it serves.
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
    manifest_url_fallback: str,
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
    2. preflights Connect *from inside the session* — ``curl`` the server URL and
       map each transport failure to a distinct tag: DNS (VIP_CONNECT_DNS),
       connect/timeout (VIP_CONNECT_UNREACHABLE), TLS trust (VIP_CONNECT_UNTRUSTED).
       The URL the pytest host reaches is not necessarily reachable from the
       Workbench server (split-horizon DNS, egress firewall, internal CA),
    3. downloads the reference manifest, trying the pinned release tag first and
       falling back to ``main`` (so an unreleased/dev version whose tag 404s still
       works); tags VIP_DL_FAIL only if *both* fail, then patches its ``platform``
       with whatever python is available,
    4. provisions ``rsconnect`` — ``uv`` (venv+install in ~1s) when present,
       else ``python -m venv`` + ``pip`` — tagging VIP_NO_PY if no interpreter and
       VIP_NO_RSCONNECT if the install itself fails (air-gapped / no PyPI mirror),
    5. runs ``rsconnect deploy manifest ... --no-verify``.

    Failure tags let the caller map environment problems to skips while real
    deploy errors stay failures:

    - VIP_CONNECT_DNS / VIP_CONNECT_UNREACHABLE / VIP_CONNECT_UNTRUSTED — the
      session cannot resolve / reach / trust the Connect URL,
    - VIP_DL_FAIL — reference manifest unreachable at both the tag and ``main``,
    - VIP_NO_PY — no python interpreter and no uv,
    - VIP_NO_RSCONNECT — an interpreter exists but rsconnect-python could not be
      installed (no PyPI or internal mirror reachable).

    Values are shlex.quote'd; the title contains spaces (unique_session_name).
    """
    app_r_b64 = base64.b64encode(app_r.encode()).decode("ascii")
    q_bundle = shlex.quote(bundle_dir)
    q_manifest = shlex.quote(manifest_path)
    q_venv = shlex.quote(venv_dir)
    q_url = shlex.quote(manifest_url)
    q_url_fallback = shlex.quote(manifest_url_fallback)
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
        # -- Preflight: can THIS session resolve / reach / trust Connect? --------
        # The URL the pytest host uses is not necessarily reachable from the
        # Workbench server. curl's exit code separates the failure classes so the
        # caller can skip with a message that names the actual constraint:
        #   6  -> DNS resolution failed         (VIP_CONNECT_DNS)
        #   60/77/35/58/59/83 -> TLS trust/cert (VIP_CONNECT_UNTRUSTED)
        #   7/28/other        -> connect/timeout(VIP_CONNECT_UNREACHABLE)
        # --head keeps it cheap; --max-time bounds a black-hole firewall.
        # Capture the rc INLINE (`|| CURL_RC=$?`): a bare `curl; CURL_RC=$?` would
        # trip `set -e` on a failing curl and abort before the rc is read.
        # No -f here: an HTTP 404/redirect at the Connect root is fine -- we are
        # testing transport + TLS trust, not the root page's status. -f is kept on
        # the manifest download below, where a 4xx genuinely means "not found".
        f"CURL_RC=0; curl -sS --head --max-time 20 -o /dev/null {q_server} || CURL_RC=$?; "
        f'if [ "$CURL_RC" != 0 ]; then '
        f'  if [ "$CURL_RC" = 6 ]; then echo VIP_CONNECT_DNS; exit 23; '
        f'  elif [ "$CURL_RC" = 60 ] || [ "$CURL_RC" = 77 ] || [ "$CURL_RC" = 35 ] '
        f'    || [ "$CURL_RC" = 58 ] || [ "$CURL_RC" = 59 ] || [ "$CURL_RC" = 83 ]; then '
        f"    echo VIP_CONNECT_UNTRUSTED; exit 24; "
        f"  else echo VIP_CONNECT_UNREACHABLE; exit 25; fi; "
        f"fi; "
        # Download the manifest: pinned release tag first, then main; only if BOTH
        # fail is it a real environment/network problem (VIP_DL_FAIL). A dev
        # checkout whose tag is not yet pushed 404s on the tag but resolves on main.
        f"curl -fsS -o {q_manifest} {q_url} "
        f"|| curl -fsS -o {q_manifest} {q_url_fallback} "
        f"|| {{ echo VIP_DL_FAIL; exit 21; }}; "
        # Patch platform if we have a python; harmless to skip if not.
        f'if [ -n "$PYBIN" ]; then {patch}; fi; '
        # Provision rsconnect: prefer uv (fast), else python venv + pip. A failed
        # install (no PyPI / internal mirror reachable, i.e. air-gapped) is an
        # environment constraint, not a publishing defect -> VIP_NO_RSCONNECT.
        # Each step guards itself with `|| { echo TAG; exit N; }` (separate
        # statements, not nested brace groups) so `set -e` cannot abort before the
        # tag is emitted -- that untagged abort is exactly the pre-fix failure.
        f"if command -v uv >/dev/null 2>&1; then "
        f"  uv venv {q_venv} >/dev/null || {{ echo VIP_NO_RSCONNECT; exit 26; }}; "
        f"  uv pip install --python {q_venv}/bin/python --quiet rsconnect-python >/dev/null "
        f"    || {{ echo VIP_NO_RSCONNECT; exit 26; }}; "
        f'elif [ -n "$PYBIN" ]; then '
        f'  "$PYBIN" -m venv {q_venv} || {{ echo VIP_NO_RSCONNECT; exit 26; }}; '
        f"  {q_venv}/bin/pip install --quiet --upgrade rsconnect-python "
        f"    || {{ echo VIP_NO_RSCONNECT; exit 26; }}; "
        f"else echo VIP_NO_PY; exit 22; fi; "
        # Deploy. --no-verify skips only rsconnect's client-side app-boot probe;
        # the command still blocks until Connect's server-side build finishes.
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
    the public repo with ``curl`` (pinned tag, falling back to ``main``) and its
    ``platform`` patched to the server's R.

    ``rsconnect-python`` is not assumed to be on PATH: the whole setup+deploy
    runs as a single shell command (see ``_build_deploy_script``) that
    provisions a throwaway venv -- preferring ``uv`` (venv + install in ~1s),
    falling back to ``python -m venv`` + ``pip`` -- deploys with that venv's
    ``rsconnect``, and the venv and bundle are torn down afterwards.

    Because the deploy runs *inside the Workbench session* (not the pytest host),
    the script preflights and tags every environment constraint on the
    session→Connect and session→PyPI axes so each maps to an actionable skip
    rather than an opaque failure: ``VIP_CONNECT_DNS`` /
    ``VIP_CONNECT_UNREACHABLE`` / ``VIP_CONNECT_UNTRUSTED`` (session cannot
    resolve/reach/trust Connect), ``VIP_DL_FAIL`` (manifest unreachable at both
    the tag and ``main``), ``VIP_NO_PY`` (no interpreter), and
    ``VIP_NO_RSCONNECT`` (interpreter present but rsconnect-python uninstallable,
    e.g. air-gapped).  A genuine ``rsconnect deploy`` failure stays a hard failure.
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
            manifest_url_fallback=shiny_bundle_spec["manifest_url_fallback"],
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
            # environment problem (Connect unreachable from the session, no
            # python/uv, no PyPI mirror, unreachable repo) to a skip while a
            # genuine rsconnect deploy failure stays a hard failure.
            msg = str(exc)
            # Dispatch on the script's EXIT CODE, not on the tag string. The
            # ExecError message embeds the whole command (``command {cmd!r} ...``),
            # and the command text literally contains every ``echo VIP_*`` tag, so
            # ``"VIP_CONNECT_DNS" in msg`` is true for *any* failure -- it would
            # mislabel a TLS/unreachable/install failure as a DNS failure. Each
            # tag has a unique exit code, which appears exactly once, so matching
            # ``exited with status <code>`` is unambiguous. The tag is still echoed
            # (visible in the captured output) for a human reading the transcript.
            code_m = re.search(r"exited with status (\d+)", msg)
            code = int(code_m.group(1)) if code_m else None
            if code == 23:
                pytest.skip(
                    f"The Workbench session cannot resolve the Connect host "
                    f"{connect_url!r} (DNS failure — the URL the test host uses may "
                    "differ from what the session can resolve, e.g. split-horizon DNS)"
                )
            if code == 24:
                pytest.skip(
                    f"The Workbench session does not trust the Connect TLS certificate "
                    f"at {connect_url!r} (self-signed / internal CA not in the session's "
                    "trust store); rsconnect would reject the connection"
                )
            if code == 25:
                pytest.skip(
                    f"The Workbench session cannot reach Connect at {connect_url!r} "
                    "(connection refused/timeout — egress firewall or internal-only "
                    "Connect hostname unreachable from the session)"
                )
            if code == 22:
                pytest.skip("Neither uv nor python3/python is available in the Workbench session")
            if code == 26:
                pytest.skip(
                    "rsconnect-python could not be installed in the Workbench session "
                    "(no PyPI or internal package mirror reachable — likely air-gapped)"
                )
            if code == 21:
                pytest.skip(
                    f"Could not download the Shiny manifest from "
                    f"{shiny_bundle_spec['manifest_url']} or its main-branch fallback "
                    f"{shiny_bundle_spec['manifest_url_fallback']} "
                    "(network/firewall constraint, or the ref does not exist)"
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


# HTTP status classification for a freshly-deployed Connect content URL,
# confirmed against posit-dev/connect serving source:
#   200            -> worker booted and is proxying (for a static-UI Shiny app,
#                     Connect only proxies AFTER the worker accepts a connection,
#                     so this is not a pre-boot loading shell); marker must render.
#   503            -> env restore / worker boot still in progress -> keep polling.
#   502            -> proxy round-trip failed (worker not yet listening or dropped);
#                     usually transient in the first seconds -> keep polling.
#   500            -> StartupError ("startup took too long" / launcher error): the
#                     app tried to boot and Connect gave up -> runtime DEFECT (fail).
#   401/403/404    -> unauthenticated / locked / API key lacks view permission
#                     (Connect returns 404, not 403, to avoid leaking existence):
#                     an auth/permission ENVIRONMENT problem, not a publish defect.
_CONNECT_BOOTING_STATUSES = frozenset({502, 503})
_CONNECT_AUTH_STATUSES = frozenset({401, 403, 404})


@then("the app is reachable on Connect")
def app_reachable_on_connect(publish_context: dict, connect_client):
    """Verify the deployed content serves a live page via the Connect API.

    Deploy runs with ``--no-verify``, so the Shiny worker may still be booting
    when the deploy command returns (the server-side build itself is already
    done — rsconnect blocks on it regardless of ``--no-verify``). Using the
    Connect API key, poll the content URL until it returns a live page (HTTP 200
    whose body carries the app's static "VIP test" marker).

    Each status is classified rather than treated as pass/keep-polling only
    (see ``_CONNECT_*`` tables): a 500 StartupError is a runtime defect and
    fails; a 401/403/404 is an auth/permission environment problem and skips; a
    502/503 is still-booting and keeps polling. The URL is always determined
    (constructed from the GUID as a last resort) so the check can never silently
    pass without actually fetching the app.
    """
    guid = publish_context.get("content_guid")
    assert guid, "No content GUID was recorded by the deploy step"

    # get_content raise_for_status()es; a transient 404/5xx immediately after
    # deploy must not crash the check, so fall back to the recorded/derived URL.
    try:
        content = connect_client.get_content(guid)
    except Exception:
        content = {}

    # Determine the content URL, never leaving it empty: recorded value first,
    # then the API's content_url, then constructed from the base URL + GUID.
    # A silent "no URL -> return" would let this step pass without a single fetch.
    url = publish_context.get("content_url") or content.get("content_url", "")
    if not url:
        base = getattr(connect_client, "base_url", "") or ""
        assert base, (
            f"Could not determine a content URL for {guid} and the Connect client "
            "exposes no base_url — cannot verify reachability"
        )
        url = f"{base.rstrip('/')}/content/{guid}/"

    _log(f"verifying live app via Connect API at {url}")
    deadline = time.monotonic() + _REACHABILITY_TIMEOUT_S
    last_status = None
    saw_startup_error = False
    while time.monotonic() < deadline:
        try:
            resp = connect_client.fetch_content(url)
            status = resp.status_code
            # 200 + rendered static marker == the app actually booted and served.
            if status == 200 and "vip test" in resp.text.lower():
                _log("live app confirmed (HTTP 200, 'VIP test' rendered)")
                return
            if status == 200:
                last_status = "200 (marker not yet rendered)"
            elif status == 500:
                # StartupError: a real runtime failure. Keep polling in case a
                # later request re-triggers a launch, but remember it so the final
                # message names the defect rather than a generic timeout.
                saw_startup_error = True
                last_status = "500 (Connect StartupError — app failed to boot)"
            elif status in _CONNECT_AUTH_STATUSES:
                pytest.skip(
                    f"Connect returned HTTP {status} for {url!r}: the API key cannot "
                    "view the deployed content (unauthenticated / locked / lacks "
                    "view permission). This is an auth/permission environment "
                    "constraint, not a publishing defect."
                )
            elif status in _CONNECT_BOOTING_STATUSES:
                last_status = f"{status} (worker still booting)"
            else:
                last_status = str(status)
        except Exception as exc:  # transient during first-boot (conn reset, etc.)
            last_status = repr(exc)
        time.sleep(_REACHABILITY_POLL_S)

    detail = (
        "the app reported a Connect StartupError (HTTP 500) and never served the "
        "'VIP test' marker — a runtime failure, not a slow boot"
        if saw_startup_error
        else f"last result: {last_status}"
    )
    raise AssertionError(
        f"Deployed content at {url!r} was not confirmed live within "
        f"{_REACHABILITY_TIMEOUT_S}s ({detail})"
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
