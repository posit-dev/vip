"""Result collection: scenario metadata, failure and skip parsing, the JSON
report and its extra formats, and the unproven exit status.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from vip.attest import UNPROVEN_SENTINEL
from vip.config import VIPConfig
from vip.plugin import state
from vip.plugin.terminal import _outcome_color
from vip.stash import (
    _auth_session_key,
    _results_key,
    _scenario_stash_key,
    _session_start_key,
    _version_na_key,
    _vip_config_key,
)

# Mapping from pytest marker name to product config key.
_PRODUCT_MARKERS = {
    "connect": "connect",
    "workbench": "workbench",
    "package_manager": "package_manager",
}

#: Exit code for a run in which nothing failed but something went unverified.
#: Deliberately distinct from pytest's own codes (0 ok, 1 failed, 2 interrupted,
#: 3 internal, 4 usage, 5 no tests collected) so a CI job can tell "the
#: deployment is broken" from "we could not check the deployment" without
#: parsing output. See ``vip.attest`` for what makes a check unproven.
EXIT_UNPROVEN = 6

#: Human-facing marker for an unproven skip. Mirrors ``reporting.UNPROVEN_PREFIX``
#: so a reason reads the same whether it came from VIP's own emitters or from a
#: reporter VIP does not control.
UNPROVEN_DISPLAY_PREFIX = "UNPROVEN: "


# ---------------------------------------------------------------------------
# JSON results for Quarto report
# ---------------------------------------------------------------------------


def _stash_scenario_metadata(item: pytest.Item) -> None:
    """Extract pytest-bdd scenario metadata and stash it on the item."""
    scenario_title = None
    feature_description = None

    # pytest-bdd stores scenario info as __scenario__ on the wrapper function.
    fn = getattr(item, "obj", None)
    scenario_obj = getattr(fn, "__scenario__", None) if fn else None
    if scenario_obj is not None:
        scenario_title = getattr(scenario_obj, "name", None)
        feature_obj = getattr(scenario_obj, "feature", None)
        if feature_obj is not None:
            feature_description = getattr(feature_obj, "description", None)

    item.stash[_scenario_stash_key] = {
        "scenario_title": scenario_title,
        "feature_description": feature_description,
    }


def _e_line_blocks(longrepr: str) -> list[list[str]]:
    """Split *longrepr* into its contiguous runs of pytest ``E`` lines.

    pytest separates the members of an exception chain with prose lines ("The
    above exception was the direct cause of the following exception:", "During
    handling of the above exception, another exception occurred:"), which are not
    ``E`` lines. One contiguous run of ``E`` lines is therefore one exception,
    and the last run is the exception the test actually raised.

    Blocking matters because a continuation line can look exactly like an
    exception header -- ``E    Connect: /metrics returned 403`` parses as type
    ``Connect`` -- so "the last thing that looks like a type" is not a safe way
    to find the last exception, but "the first line of the last block" is.
    """
    blocks: list[list[str]] = []
    in_block = False
    for line in longrepr.splitlines():
        if re.match(r"^E\s", line):
            if not in_block:
                blocks.append([])
            blocks[-1].append(line)
            in_block = True
        else:
            in_block = False
    return blocks


def _parse_e_block(block: list[str]) -> tuple[str, str] | None:
    """Parse one ``E``-line block into ``(exception_type, message)``, or None.

    The block's first line carries the type; the remaining lines are
    continuation text belonging to it.
    """
    head, rest = block[0], block[1:]

    # "E   ExcType: message" (message may be empty). Continuation lines are
    # joined so multi-line assertion detail survives into the concise output.
    m = re.match(r"^E\s+([\w.]+(?:Error|Exception|Timeout|Refused)?):\s*(.*)", head)
    if m:
        msg_lines = [m.group(2).strip()]
        for line in rest:
            cont = re.match(r"^E\s{3,}(.+)", line)
            if not cont:
                break
            msg_lines.append(cont.group(1).strip())
        return m.group(1), "\n".join(line for line in msg_lines if line)

    # Bare assertion from pytest's assertion rewriting: "E   assert 403 == 200".
    m = re.match(r"^E\s+(assert\s+.+)", head)
    if m:
        return "AssertionError", m.group(1).strip()

    # Bare exception type with no message: "E   ValueError" (no colon).
    m = re.match(r"^E\s+([\w.]+(?:Error|Exception|Timeout|Refused)?)\s*$", head)
    if m:
        return m.group(1), ""

    return None


def _extract_exception_info(longrepr: str) -> tuple[str, str]:
    """Extract (exception_type, message) from a longrepr string.

    Handles four common formats:
    - pytest's ``E   ExcType: message`` lines in tracebacks
    - pytest's bare ``E   assert ...`` lines (assertion rewriting, no type prefix)
    - pytest's bare ``E   ExcType`` lines (exception with no message)
    - plain ``ExcType: message`` strings (e.g. from failures.json)

    For a chained failure (``raise X from Y``, or an exception raised while
    handling another) the *last* ``E`` block is reported, because that is the
    exception the code actually raised. pytest prints the cause first, so
    reporting the first block reports the cause and discards the diagnosis the
    raising code built -- live, an RStudio console failure reported Playwright's
    multi-kilobyte locator dump while the ExecError naming the real reason never
    appeared anywhere in the report.

    Returns ``("UnknownError", <truncated string>)`` if parsing fails.
    """
    # Walk the chain backwards: the raised exception first, falling back to
    # earlier members if the last block is not in a recognised shape.
    for block in reversed(_e_line_blocks(longrepr)):
        parsed = _parse_e_block(block)
        if parsed:
            return parsed

    # Fall back to "ExcType: message" at the start of the string.
    m = re.match(r"([\w.]+(?:Error|Exception|Timeout|Refused)?):\s*(.+)", longrepr.strip())
    if m:
        return m.group(1), m.group(2).strip()

    return "UnknownError", longrepr.strip()[:200]


_SKIPPED_PREFIX = "Skipped: "


def _classify_skip_reason(reason: str | None) -> tuple[str | None, bool]:
    """Split a skip reason into its human-readable text and its classification.

    ``vip.attest.unproven`` prefixes the reason with a sentinel so the
    classification survives the trip from the skip site to here (see that
    module for why the reason string is the transport). This strips it back
    off, so the sentinel never reaches a report, a terminal line, or a user.

    Returns ``(reason_without_sentinel_or_None, is_unproven)``. The sentinel
    must be a *prefix* -- a reason that merely quotes it is not a
    classification.
    """
    if reason is None:
        return None, False
    if not reason.startswith(UNPROVEN_SENTINEL):
        return reason, False
    stripped = reason[len(UNPROVEN_SENTINEL) :].strip()
    return (stripped or None), True


def _extract_skip_reason(longrepr: object) -> str | None:
    """Pull the human-readable reason out of a skip report's ``longrepr``.

    For a skip, pytest hands back ``report.longrepr`` as a 3-tuple
    ``(path, lineno, message)`` where ``message`` is ``"Skipped: <reason>"`` —
    that shape is what ``pytest.mark.skip(reason=...)``, a bare
    ``pytest.skip(...)`` call, and ``_skip_version_unknown``'s marker-based
    skip all produce, so this one path also covers ``na_version`` skips. We
    read the tuple directly rather than regex-parsing ``str(report.longrepr)``
    — the whole point is to avoid the absolute source path that stringified
    form embeds in element 0 (see ``TestResult.skip_reason``'s docstring).
    A plain string or ``None`` (unusual, but not ruled out by pytest's own
    typing) is handled too. Anything else falls back to ``None`` instead of
    guessing at a shape we haven't seen.
    """
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        message = longrepr[2]
    elif isinstance(longrepr, str) or longrepr is None:
        message = longrepr
    else:
        return None
    if not isinstance(message, str) or not message:
        return None
    if message.startswith(_SKIPPED_PREFIX):
        message = message[len(_SKIPPED_PREFIX) :]
    # Strip before the emptiness check, not after: "Skipped:    " and a
    # ``reason="   "`` both leave whitespace once the prefix is removed, and a
    # truthy-but-blank reason renders as an empty line in the report rather
    # than falling back to the "no reason recorded" wording.
    return message.strip() or None


def _format_concise_error(
    nodeid: str,
    exc_type: str,
    exc_message: str,
) -> str:
    """Format a concise one-liner error message for terminal and report display.

    AssertionError is treated as an expected test failure — the message is shown
    directly. All other exception types are prefixed with "an unexpected error
    occurred" to signal infrastructure or code issues.
    """
    test_name = nodeid.rsplit("::", maxsplit=1)[-1] if "::" in nodeid else nodeid

    is_assertion = exc_type == "AssertionError" or exc_type.endswith(".AssertionError")

    if not exc_message:
        if is_assertion:
            return f"{test_name}: {exc_type}"
        return f"{test_name}: an unexpected error occurred: {exc_type}"

    if is_assertion:
        # Custom assertion messages are user-actionable — show them directly.
        # Bare assertions (e.g. "assert 403 == 200") still need the type prefix.
        if exc_message.lstrip().startswith("assert "):
            return f"{test_name}: AssertionError: {exc_message}"
        return f"{test_name}: {exc_message}"

    return f"{test_name}: an unexpected error occurred: {exc_type}: {exc_message}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call):  # noqa: ARG001
    """Attach VIP metadata to the report so it survives xdist serialization.

    Under xdist, ``TestReport.__dict__`` is serialized and sent from worker
    to controller.  Custom attributes set here travel with the report, making
    them available in ``pytest_runtest_logreport`` on the controller where
    result collection happens.
    """
    outcome = yield
    report: pytest.TestReport = outcome.get_result()
    if state._active_config is None:
        return
    if report.when == "call" or (report.when == "setup" and report.skipped):
        markers: list[str] = []
        try:
            markers = [m.name for m in item.iter_markers()]
        except Exception:  # noqa: BLE001
            pass

        item_stash = getattr(item, "stash", None)
        scenario_meta: dict[str, str | None] = {}
        na_version = False
        if item_stash is not None:
            scenario_meta = item_stash.get(_scenario_stash_key, {})
            na_version = item_stash.get(_version_na_key, False)

        # These attributes survive xdist worker→controller serialization.
        report.vip_markers = markers  # type: ignore[attr-defined]
        report.vip_scenario_title = scenario_meta.get("scenario_title")  # type: ignore[attr-defined]
        report.vip_feature_description = scenario_meta.get("feature_description")  # type: ignore[attr-defined]
        report.vip_na_version = na_version  # type: ignore[attr-defined]


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Collect results for JSON report and apply concise terminal display.

    Under xdist, ``pytest_runtest_makereport`` runs on workers but the
    controller never sees the worker's stash.  This hook fires on the
    controller for every forwarded result (via ``dsession.worker_testreport``),
    making it the right place to aggregate results.  The ``workerinput``
    guard skips processing on workers so results are collected exactly once.
    """
    # Strip the xdist worker attribute so pytest's built-in TerminalReporter
    # does not prefix each verbose line with ``[gw<N>]`` and instead writes
    # the location and outcome together in one line (see
    # ``pytest_runtest_logstart`` above for why that requires suppressing
    # the pre-test location line too).  Runs before the terminal reporter
    # thanks to ``tryfirst=True``.
    if hasattr(report, "node"):
        del report.node

    if state._active_config is None:
        return

    # On xdist workers, skip all processing — the controller handles it.
    # _active_config is a pytest.Config; xdist sets workerinput on worker configs.
    if hasattr(state._active_config, "workerinput"):
        return

    # Classify the skip and rewrite its reason in place, before anything else
    # reads it. Downstream reporters we do not own -- pytest's own --junitxml
    # above all, which ci.yml and the smoke workflows pass directly -- render
    # report.longrepr verbatim, so leaving the sentinel there would publish an
    # internal transport detail into an uploaded artifact that AGENTS.md
    # explicitly tells operators to read skip reasons out of. Rewriting to the
    # display prefix instead means those reporters show the classification too.
    #
    # This runs after the worker guard on purpose: the sentinel is how the
    # classification survives the trip from an xdist worker to the controller,
    # since custom report attributes are not serialised across that boundary.
    # Strip it once, here, where the JUnit XML is actually written.
    if report.skipped:
        _skip_reason, _unproven = _classify_skip_reason(_extract_skip_reason(report.longrepr))
        report.vip_skip_reason = _skip_reason  # type: ignore[attr-defined]
        report.vip_unproven = _unproven  # type: ignore[attr-defined]
        if _unproven:
            _display = f"{UNPROVEN_DISPLAY_PREFIX}{_skip_reason or 'could not verify'}"
            # Keep pytest's 3-tuple shape: _pytest.junitxml asserts on it.
            if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
                _path, _lineno, _ = report.longrepr
                report.longrepr = (_path, _lineno, f"{_SKIPPED_PREFIX}{_display}")
            else:
                report.longrepr = _display

    # Capture this line's color for the progress-indicator recolor wrapper.
    # tryfirst ensures this runs before the terminal reporter renders the same
    # report, so the trailing ``[ x%]`` picks up this line's own outcome.
    state._current_line_color = _outcome_color(report)

    # --- Result collection (for JSON report) ---
    if report.when == "call" or (report.when == "setup" and report.skipped):
        results = state._active_config.stash.get(_results_key, None)
        if results is not None:
            longrepr_str = str(report.longrepr) if report.longrepr else None
            concise_error = None
            skip_reason = None
            unproven = False
            if report.outcome == "failed" and longrepr_str:
                exc_type, exc_message = _extract_exception_info(longrepr_str)
                concise_error = _format_concise_error(report.nodeid, exc_type, exc_message)
            elif report.outcome == "skipped":
                # Already classified above; re-parsing here would read back the
                # rewritten reason and double-prefix it.
                skip_reason = getattr(report, "vip_skip_reason", None)
                unproven = getattr(report, "vip_unproven", False)
                # Stringified longrepr is pytest's raw ``(path, lineno, "Skipped:
                # ...")`` tuple and leaks the absolute path of the file that
                # called skip() into results.json (an uploaded CI artifact).
                # skip_reason above already carries the part worth keeping, so
                # don't also store the leaky form for skips.
                longrepr_str = None

            results.append(
                {
                    "nodeid": report.nodeid,
                    "outcome": report.outcome,
                    "duration": report.duration,
                    "longrepr": longrepr_str,
                    "concise_error": concise_error,
                    "skip_reason": skip_reason,
                    "markers": list(getattr(report, "vip_markers", ())),
                    "scenario_title": getattr(report, "vip_scenario_title", None),
                    "feature_description": getattr(report, "vip_feature_description", None),
                    "na_version": getattr(report, "vip_na_version", False),
                    "unproven": unproven,
                }
            )

    # --- Concise terminal display ---
    if state._active_config.getoption("--vip-verbose", default=False):
        return
    if report.outcome not in ("failed", "error"):
        return
    if not report.longrepr:
        return

    longrepr_str = str(report.longrepr)
    exc_type, exc_message = _extract_exception_info(longrepr_str)
    report.longrepr = _format_concise_error(report.nodeid, exc_type, exc_message.replace("\n", " "))


def _emit_extra_formats(fmt: str, results_path: Path) -> None:
    """Emit JUnit/SARIF siblings of results_path per a comma-separated format list.

    ``results.json`` is always written by the caller; this only adds the extra
    machine-readable formats. Unknown format tokens are non-fatal: known formats
    are still emitted, and a warning is raised for each unrecognized token.
    """
    from vip.reporting import VALID_FORMATS, load_results, write_junit_xml, write_sarif

    formats = {f.strip().lower() for f in fmt.split(",") if f.strip()}
    unknown = formats - VALID_FORMATS
    if unknown:
        warnings.warn(
            f"VIP: ignoring unknown --vip-format value(s): {', '.join(sorted(unknown))}",
            stacklevel=2,
        )
    if not (formats & {"junit", "sarif"}):
        return
    data = load_results(results_path)
    if "junit" in formats:
        write_junit_xml(data, results_path.parent / "junit.xml")
    if "sarif" in formats:
        write_sarif(data, results_path.parent / "results.sarif")


def _apply_unproven_exit_status(session: pytest.Session, exitstatus: int) -> int:
    """Fail the run when checks went unproven, and return the effective status.

    Only promotes a status of 0. A real failure is the stronger signal and
    must not be masked -- if pytest already decided the run failed, that
    verdict stands. ``--vip-allow-unproven`` opts out entirely.

    Mutates ``session.exitstatus`` so the process exit code follows, and
    returns the new value so the caller records the same number in
    results.json rather than the stale one pytest passed in.
    """
    if exitstatus != 0:
        return exitstatus
    if session.config.getoption("--vip-allow-unproven", default=False):
        return exitstatus
    results = session.config.stash.get(_results_key, None) or []
    unproven = [r for r in results if r.get("unproven")]
    if not unproven:
        return exitstatus

    session.exitstatus = EXIT_UNPROVEN
    reasons = "\n".join(
        f"  - {r['nodeid']}: {r.get('skip_reason') or 'no reason recorded'}" for r in unproven
    )
    print(
        f"\nVIP: {len(unproven)} check(s) could not be verified. Nothing failed, "
        f"but nothing was proven either:\n{reasons}\n"
        "Pass --vip-allow-unproven (or --allow-unproven via `vip verify`) "
        "to treat these as an ordinary skip.",
        file=sys.stderr,
    )
    return EXIT_UNPROVEN


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Clean up the auth session, apply the unproven exit status, and write the report.

    Runs only on the xdist controller (workers return early after skipping cleanup).
    Writes ``report/results.json`` (or the ``--vip-report`` path) plus any junit/sarif
    siblings requested via ``--vip-format``, unless ``--vip-report`` is empty.
    """
    # xdist workers skip all session-end cleanup (controller handles it).
    is_worker = hasattr(session.config, "workerinput")

    if not is_worker:
        # Clean up interactive auth session (delete API key, remove temp files)
        auth_session = session.config.stash.get(_auth_session_key, None)
        if auth_session is not None:
            auth_session.cleanup()

    if not is_worker:
        exitstatus = _apply_unproven_exit_status(session, exitstatus)

    report_path = session.config.getoption("--vip-report")
    if not report_path or is_worker:
        return

    cfg: VIPConfig = session.config.stash[_vip_config_key]
    results = session.config.stash.get(_results_key, [])

    # Include product metadata for the report.
    # Derive product list from _PRODUCT_MARKERS so new products are picked up automatically.
    products: dict[str, dict[str, Any]] = {}
    for name in _PRODUCT_MARKERS.values():
        pc = cfg.product_config(name)
        products[name] = {
            "enabled": pc.enabled,
            "url": pc.url,
            "version": pc.version,
            "configured": pc.is_configured,
        }

    from vip import __version__ as vip_version

    session_start = session.config.stash.get(_session_start_key, None)
    run_duration_seconds = time.monotonic() - session_start if session_start is not None else None
    # There is no dedicated "--basic" flag on the plugin side — `vip verify
    # --basic` (vip/cli/verify.py) maps to the generic pytest `-m` marker expression,
    # appending "not slow" to whatever categories/markers were already
    # selected. Detecting that from here means reading the resolved
    # expression back rather than a purpose-built flag, but it is also the
    # more honest signal: it reflects "was the slow marker actually excluded",
    # true for any run that got there via `-m "not slow"` directly too, not
    # just ones that went through `--basic`.
    basic_mode = "not slow" in (session.config.getoption("markexpr", default="") or "")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "deployment_name": cfg.deployment_name,
        "exit_status": exitstatus,
        "vip_version": vip_version,
        "run_duration_seconds": run_duration_seconds,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "basic_mode": basic_mode,
        "products": products,
        "results": results,
    }

    try:
        p = Path(report_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    except OSError as exc:
        warnings.warn(f"VIP: could not write report to {report_path}: {exc}", stacklevel=1)
        return

    fmt = session.config.getoption("--vip-format", default="json")
    try:
        _emit_extra_formats(fmt, p)
    except (OSError, ValueError, KeyError) as exc:
        warnings.warn(f"VIP: could not write extra formats: {exc}", stacklevel=1)

    # Write failures.json alongside results.json so report rendering is idempotent.
    failures = [r for r in results if r.get("outcome") == "failed"]
    if failures:
        failures_payload = {
            "deployment": cfg.deployment_name,
            "generated_at": payload["generated_at"],
            "failures": [
                {
                    "test": r["nodeid"],
                    "scenario": r.get("scenario_title"),
                    "feature": r.get("feature_description"),
                    "error_summary": r.get("concise_error") or (r.get("longrepr") or "")[:500],
                }
                for r in failures
            ],
        }
        failures_path = p.parent / "failures.json"
        try:
            failures_path.write_text(json.dumps(failures_payload, indent=2) + "\n")
        except OSError as exc:
            warnings.warn(
                f"VIP: could not write failures report to {failures_path}: {exc}", stacklevel=1
            )
