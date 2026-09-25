"""Scaled Playwright timeout constants and session-poll settings for Workbench tests.

Imports nothing from the other Workbench modules, so every one of them can
depend on it. ``conftest.py`` re-exports these names for the step files.
"""

from __future__ import annotations

from vip.timeouts import timeout_scale

# ---------------------------------------------------------------------------
# Playwright timeout constants (milliseconds)
# Scaled at definition time so all 9 importing step files pick up the scale
# without any call-site changes.  Set VIP_TIMEOUT_SCALE=N before running.
# ---------------------------------------------------------------------------

TIMEOUT_QUICK = int(5_000 * timeout_scale())
TIMEOUT_DIALOG = int(10_000 * timeout_scale())
TIMEOUT_PAGE_LOAD = int(15_000 * timeout_scale())
TIMEOUT_CLEANUP = int(30_000 * timeout_scale())
TIMEOUT_CODE_EXEC = int(30_000 * timeout_scale())
TIMEOUT_IDE_LOAD = int(60_000 * timeout_scale())
TIMEOUT_SESSION_START = int(90_000 * timeout_scale())
# The silent-SSO click-through in _silent_sso_signin used TIMEOUT_PAGE_LOAD
# (15s) until issue #263's diagnostic showed a SAML round-trip (IdP redirect,
# assertion POST, Workbench's own validation) taking longer than that under
# real IdP latency, which read as "no usable IdP session" and skipped a
# login that was actually still completing.
TIMEOUT_SSO_ROUNDTRIP = int(60_000 * timeout_scale())
# Short window to detect whether an optional confirm/force-quit dialog appeared
# in the UI session sweep. Used to gate (not to click) so an absent dialog does
# not cost TIMEOUT_QUICK each iteration; a dialog that does appear is then
# clicked with the normal TIMEOUT_QUICK.
TIMEOUT_DIALOG_PROBE = int(1_000 * timeout_scale())

# Poll interval (ms) used while waiting for a session to reach Active.
_SESSION_POLL_INTERVAL = 500

# Session statuses that are terminal failures: the session has stopped and
# will never reach Active, so continuing to wait is pointless.  Detecting one
# of these lets the session-start wait fail fast with an actionable message
# instead of timing out on an opaque "Locator expected to be visible" error.
TERMINAL_SESSION_FAILURE_STATES = ("Failed",)
