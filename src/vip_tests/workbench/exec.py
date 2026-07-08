"""In-session execution primitives for Workbench IDE tests.

All helpers use **marker-bracketed capture**: each caller's expression is
wrapped with a unique UUID sentinel so its output can be reliably extracted
from the accumulated console scrollback.

Architecture layers used by this module:
- Layer 2 (DSL): this module — called from step definitions
- Layer 3 (Driver Port): delegates to page-object selectors in pages/
- Layer 4 (Driver Adapter): Playwright (via the Page parameter)

Pure helpers (_wrap_r_expr, _wrap_python_expr, _extract_between_markers,
_strip_r_index) are fully unit-testable without Playwright and are covered
by selftests/test_workbench_exec.py.
"""

from __future__ import annotations

import re
import time
import uuid

from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from vip_tests.workbench.pages import (
    ConsolePaneSelectors,
    JupyterLabSession,
    PositronSession,
    RStudioSession,
    VSCodeSession,
)


class ExecError(RuntimeError):
    """Raised when an expression evaluation fails or its output cannot be captured."""


# ---------------------------------------------------------------------------
# Pure helpers — unit-testable without Playwright
# ---------------------------------------------------------------------------


def _make_sentinels() -> tuple[str, str]:
    """Return a unique (start_marker, end_marker) pair for one eval call."""
    uid = uuid.uuid4().hex
    return f"<<VIP-START-{uid}>>", f"<<VIP-END-{uid}>>"


def _split_marker(marker: str) -> tuple[str, str]:
    """Split *marker* into two non-empty halves.

    The wrap helpers emit the two halves as separate, concatenated string
    literals so the *typed* statement never contains the full contiguous
    marker — only the *executed* output does.  This matters because consoles
    (RStudio, Positron) echo the typed input into the same pane we read back
    from: if the literal marker appeared in the echo, both the readiness wait
    (``to_contain_text(end)``) and ``_extract_between_markers`` would match the
    echoed input instead of the command's output.
    """
    k = max(1, len(marker) // 2)
    return marker[:k], marker[k:]


def _wrap_r_expr(expr: str, start: str, end: str) -> str:
    """Wrap *expr* in a semicolon-chained R statement fenced with VIP markers.

    Produces a single-line statement safe to type into the RStudio / Positron
    console input without triggering continuation prompts.

    Each sub-expression in a semicolon chain is auto-printed at the R REPL,
    so visible-valued expressions (e.g. ``1 + 1``, ``packageVersion('Matrix')``)
    print their result between the markers.

    The markers are emitted as two concatenated ``cat`` arguments so the typed
    source does not contain the full marker (see ``_split_marker``); the printed
    output still contains it contiguously.

    Example output::

        cat("<<VIP-STA", "RT-abc>>\\n", sep=""); 1 + 1; cat("\\n", "<<VIP-E", "ND-abc>>\\n", sep="")
    """
    s1, s2 = _split_marker(start)
    e1, e2 = _split_marker(end)
    return f'cat("{s1}", "{s2}\\n", sep=""); {expr}; cat("\\n", "{e1}", "{e2}\\n", sep="")'


def _wrap_python_expr(expr: str, start: str, end: str) -> str:
    """Wrap *expr* with Python print() markers.

    Returns a newline-separated block suitable for pasting into a JupyterLab
    cell or a Positron Python console as a single execution unit.

    The markers use Python implicit string-literal concatenation (``"a" "b"``)
    so the typed source does not contain the full contiguous marker, only the
    printed output does (see ``_split_marker``).

    Example output (3 lines)::

        print("<<VIP-STA" "RT-abc>>")
        <expr>
        print("<<VIP-E" "ND-abc>>")
    """
    s1, s2 = _split_marker(start)
    e1, e2 = _split_marker(end)
    return f'print("{s1}" "{s2}")\n{expr}\nprint("{e1}" "{e2}")'


def _extract_between_markers(text: str, start: str, end: str) -> str:
    """Return the text between *start* and *end*, stripped of surrounding whitespace.

    Raises ExecError if either marker is absent in *text*.
    """
    s = text.find(start)
    if s == -1:
        raise ExecError(f"Start marker not found in captured output (marker={start!r})")
    e = text.find(end, s + len(start))
    if e == -1:
        raise ExecError(f"End marker not found in captured output (marker={end!r})")
    return text[s + len(start) : e].strip()


def _strip_r_index(text: str) -> str:
    """Strip R's vector-index prefix (e.g. ``[1]``) from the start of each line.

    Useful when the caller only cares about the value, not R's display format.
    Returns empty string when *text* is empty.

    For example, ``[1] 1.0.6`` becomes ``1.0.6``.
    """
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"^\[\d+\]\s*", "", line) if re.match(r"^\[\d+\]", line) else line)
    return "\n".join(lines).strip()


def _parse_done_marker(content: str, done_marker: str) -> tuple[str, int] | None:
    """Look for a ``{done_marker}:<exit_code>`` line in *content*.

    ``terminal_run`` writes this marker unconditionally, with the command's
    exit code appended, so a fast failure can be told apart from "still
    running" (see issue #439 -- a marker written only via ``&&`` never
    appears when the command exits non-zero).

    Returns:
        ``(captured_output, exit_code)`` with the marker line removed, or
        ``None`` if the marker has not appeared in *content* yet.
    """
    prefix = f"{done_marker}:"
    lines = content.splitlines()
    for line in lines:
        if line.strip().startswith(prefix):
            exit_code = int(line.strip()[len(prefix) :])
            output = "\n".join(ln for ln in lines if ln.strip() != line.strip())
            return output.strip(), exit_code
    return None


# ---------------------------------------------------------------------------
# Console / cell eval primitives
# ---------------------------------------------------------------------------


def rstudio_eval(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as R in the RStudio console and return the captured output.

    Uses marker-bracketed capture to isolate this expression's output from all
    prior scrollback in the console pane.  Waits up to *timeout* milliseconds
    for the end marker to appear before raising ExecError.

    Args:
        page: Playwright page for an active RStudio session.
        expr: R expression (single line or semicolon-chained).
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.

    Raises:
        ExecError: End marker did not appear within *timeout* — typically means
            a startup script (e.g. an ``.Rprofile`` with an interactive
            Acceptable-Usage-Policy prompt) is blocking the console before it
            can accept input.
        PlaywrightTimeoutError: Console input was not visible within *timeout*.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_r_expr(expr, start, end)

    # Ensure the Console tab is active. Console and Terminal are tabs in the
    # same RStudio pane, so a prior terminal_run may have left the Terminal tab
    # selected, which hides the console input and would stall this readback.
    console_tab = page.locator(ConsolePaneSelectors.TAB)
    if console_tab.count() > 0:
        console_tab.click()

    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    console_input.type(wrapped)
    console_input.press("Enter")

    console_output = page.locator(ConsolePaneSelectors.OUTPUT)
    try:
        expect(console_output).to_contain_text(end, timeout=timeout)
    except PlaywrightTimeoutError as exc:
        raise ExecError(
            "R console did not return the expected output within "
            f"{timeout} ms. A startup script (e.g. an .Rprofile with an "
            "interactive Acceptable-Usage-Policy prompt) may be blocking the "
            "console before it can accept input."
        ) from exc

    text = console_output.text_content() or ""
    return _extract_between_markers(text, start, end)


# Positron console selectors — confirmed live via posit-dev/positron/test/e2e/pages/console.ts
# and READBACK-MECHANISM.md (issue #386).
_POSITRON_ACTIVE_CONSOLE = PositronSession.ACTIVE_CONSOLE
_POSITRON_CONSOLE_INPUT = PositronSession.CONSOLE_INPUT
_POSITRON_CONSOLE_LINES = f"{PositronSession.ACTIVE_CONSOLE} div span"
_POSITRON_CONSOLE_READY = f"{PositronSession.ACTIVE_CONSOLE} .active-line-number"
# The Console and Terminal share the bottom panel; a prior terminal_run leaves
# the Terminal tab selected, hiding the console. Activate the Console tab first.
_POSITRON_CONSOLE_TAB = PositronSession.CONSOLE_TAB


def _activate_positron_console(page: Page) -> None:
    """Click the Positron Console tab so the console panel is shown.

    ``terminal_run`` runs the command in the Terminal tab, which hides the
    Console; the console readback must re-activate it (analogous to
    ``rstudio_eval`` clicking the RStudio Console tab). Best-effort.
    """
    tab = page.locator(_POSITRON_CONSOLE_TAB)
    if tab.count() > 0:
        try:
            tab.first.click()
        except Exception:
            pass


# Settle wait (ms) after the interpreter's active-line-number is visible.
# Typing during "R 4.4.0 starting." is silently dropped; this pause lets the
# REPL reach the interactive prompt before we type the wrapped expression.
_POSITRON_SETTLE_MS = 3_000


def positron_eval_r(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as R in the Positron console and return the captured output.

    Uses marker-bracketed capture against the active Positron console instance
    (``.console-instance[style*="z-index: auto"]``).  Waits for the interpreter
    to reach the interactive prompt before typing to avoid dropped keystrokes
    during startup.

    Args:
        page: Playwright page for an active Positron session.
        expr: R expression (single line or semicolon-chained).
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_r_expr(expr, start, end)

    _activate_positron_console(page)
    active = page.locator(_POSITRON_ACTIVE_CONSOLE)
    expect(active.first).to_be_visible(timeout=timeout)

    # Wait for the interpreter to be INPUT-ready before typing.
    expect(active.locator(".active-line-number").first).to_be_visible(timeout=timeout)
    page.wait_for_timeout(_POSITRON_SETTLE_MS)

    ci = active.locator(_POSITRON_CONSOLE_INPUT).first
    ci.click()
    page.keyboard.type(wrapped)
    page.keyboard.press("Enter")

    # Poll the joined span text until the end marker appears.
    deadline = time.monotonic() + timeout / 1000.0
    while time.monotonic() < deadline:
        spans = active.locator("div span").all_text_contents()
        joined = "".join(spans)
        if end in joined:
            return _extract_between_markers(joined, start, end)
        time.sleep(0.5)

    raise ExecError(
        f"Positron R console did not return the expected output within {timeout} ms "
        f"(end marker {end!r} not found)."
    )


def positron_eval_python(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as Python in the Positron console and return the captured output.

    Uses the same active-console selectors as ``positron_eval_r``.  Submits the
    wrapped multi-line expression line-by-line (Enter between lines) as the
    console requires each line to be individually submitted.

    Args:
        page: Playwright page for an active Positron session.
        expr: Python expression or statement.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_python_expr(expr, start, end)

    _activate_positron_console(page)
    active = page.locator(_POSITRON_ACTIVE_CONSOLE)
    expect(active.first).to_be_visible(timeout=timeout)

    # Wait for the interpreter to be INPUT-ready before typing.
    expect(active.locator(".active-line-number").first).to_be_visible(timeout=timeout)
    page.wait_for_timeout(_POSITRON_SETTLE_MS)

    ci = active.locator(_POSITRON_CONSOLE_INPUT).first
    ci.click()
    # Submit each line separately; Enter submits a complete statement in the Python REPL.
    for line in wrapped.splitlines():
        page.keyboard.type(line)
        page.keyboard.press("Enter")

    # Poll the joined span text until the end marker appears.
    deadline = time.monotonic() + timeout / 1000.0
    while time.monotonic() < deadline:
        spans = active.locator("div span").all_text_contents()
        joined = "".join(spans)
        if end in joined:
            return _extract_between_markers(joined, start, end)
        time.sleep(0.5)

    raise ExecError(
        f"Positron Python console did not return the expected output within {timeout} ms "
        f"(end marker {end!r} not found)."
    )


def jupyterlab_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30_000) -> str:
    """Evaluate *expr* in a JupyterLab notebook cell and return the captured output.

    Assumes the JupyterLab launcher or notebook panel is already visible.
    Clicks the first available code cell input, types the wrapped expression,
    and runs it with Shift+Enter.

    Args:
        page: Playwright page for an active JupyterLab session.
        expr: Code expression (Python or R depending on *lang*).
        lang: ``"python"`` (default) or ``"r"`` — controls marker wrapping.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    if lang.lower() == "r":
        wrapped = _wrap_r_expr(expr, start, end)
    else:
        wrapped = _wrap_python_expr(expr, start, end)

    cell_input = page.locator(JupyterLabSession.CELL_INPUT).first
    expect(cell_input).to_be_visible(timeout=timeout)
    cell_input.click()

    # For Python, type each line and press Enter to build a multi-line cell.
    # For R, the wrapped expression is a single line; type it directly.
    if lang.lower() == "python":
        for line in wrapped.splitlines():
            cell_input.type(line)
            cell_input.press("Enter")
    else:
        cell_input.type(wrapped)

    cell_input.press("Shift+Enter")

    cell_output = page.locator(JupyterLabSession.CELL_OUTPUT).last
    expect(cell_output).to_contain_text(end, timeout=timeout)

    text = cell_output.text_content() or ""
    return _extract_between_markers(text, start, end)


# ---------------------------------------------------------------------------
# VS Code editor-open readback helpers
# ---------------------------------------------------------------------------


def _focus_explorer(page: Page) -> None:
    """Click the Explorer activity-bar tab to move focus off the terminal.

    When the terminal has focus, ``Meta+Shift+P`` / ``Control+Shift+P`` is
    intercepted by the shell rather than opening the command palette.  Clicking
    Explorer first reliably defocuses the terminal.
    """
    try:
        page.get_by_role("tab", name=re.compile(r"Explorer", re.I)).first.click()
    except Exception:
        # Fallback: click the first action item in the activity bar.
        try:
            page.locator(".activitybar .actions-container .action-item").first.click()
        except Exception:
            pass


def _dismiss_workspace_trust(page: Page) -> None:
    """Dismiss the Workspace Trust dialog if it is present.

    VS Code shows this dialog when opening files from ``/tmp`` or other paths
    outside the current workspace.  Clicking "Open" grants trust for the window
    session.  Idempotent — no-op when the dialog is absent.
    """
    dialog_block = page.locator(".monaco-dialog-modal-block")
    if dialog_block.count() == 0:
        return
    # Try the "Open" button first (exact text), then fall back to open/trust/yes.
    buttons = dialog_block.locator(".dialog-buttons .monaco-button")
    count = buttons.count()
    for i in range(count):
        btn = buttons.nth(i)
        text = (btn.text_content() or "").strip()
        if text == "Open":
            btn.click()
            return
    for i in range(count):
        btn = buttons.nth(i)
        text = (btn.text_content() or "").strip().lower()
        if re.search(r"open|trust|yes", text):
            btn.click()
            return


def _open_file_in_vscode_editor(page: Page, abspath: str, timeout: int = 30_000) -> None:
    """Open *abspath* in the Monaco editor via the command palette.

    Uses ``>File: Open File`` in the command palette, filling the absolute
    path into the path input.  Dismisses the Workspace Trust dialog afterward.
    Mac keybinding (``Meta+Shift+P``) is tried first; ``Control+Shift+P`` is
    the fallback for Linux sessions.
    """
    _focus_explorer(page)

    # Try Meta+Shift+P (Mac keybinding), fall back to Control+Shift+P.
    page.keyboard.press("Meta+Shift+P")
    pal = page.locator(".quick-input-box input")
    try:
        pal.wait_for(state="visible", timeout=3_000)
    except PlaywrightTimeoutError:
        page.keyboard.press("Control+Shift+P")
        pal.wait_for(state="visible", timeout=timeout)

    pal.fill(">File: Open File")
    page.wait_for_timeout(300)
    pal.press("Enter")
    page.wait_for_timeout(300)

    fp = page.locator(".quick-input-box input")
    fp.wait_for(state="visible", timeout=timeout)
    fp.fill(abspath)
    page.wait_for_timeout(300)
    fp.press("Enter")
    page.wait_for_timeout(500)

    _dismiss_workspace_trust(page)


def _read_vscode_editor_text(page: Page, timeout: int = 30_000) -> str:
    """Return the inner text of the active Monaco editor view-lines."""
    loc = page.locator(".editor-instance .view-lines").first
    expect(loc).to_be_visible(timeout=timeout)
    return loc.inner_text()


def _close_active_editor(page: Page) -> None:
    """Close the currently active editor tab.

    Used to force a fresh re-open so the editor re-reads file contents from
    disk on the next ``_open_file_in_vscode_editor`` call.
    """
    try:
        page.keyboard.press("Meta+W")
    except Exception:
        try:
            page.keyboard.press("Control+W")
        except Exception:
            pass
    page.wait_for_timeout(200)


def read_file_via_vscode_editor(page: Page, path: str, timeout: int = 30_000) -> str:
    """Read *path* from the Workbench server by opening it in the Monaco editor.

    Opens the file via the command palette (``>File: Open File``), reads the
    ``.view-lines`` text, and returns it.  The file is read once per call;
    callers that need to re-read a growing file should call this function again
    (each call closes and re-opens the tab to force a fresh disk read).

    Args:
        page: Playwright page for an active VS Code session.
        path: Absolute server-side file path to open.
        timeout: Max milliseconds to wait for the editor to render.

    Returns:
        File contents as a string.
    """
    _open_file_in_vscode_editor(page, path, timeout=timeout)
    return _read_vscode_editor_text(page, timeout=timeout)


# ---------------------------------------------------------------------------
# IDE detection helper
# ---------------------------------------------------------------------------


def _detect_ide(page: Page) -> str:
    """Identify which IDE is rendered on *page*.

    Positron and VS Code both render ``.monaco-workbench``; Positron is
    distinguished first by its unique ``.positron-console`` panel. Returns one
    of ``"rstudio"``, ``"positron"``, ``"vscode"``, or ``"unknown"``.
    """
    if page.locator(RStudioSession.CONTAINER).count() > 0:
        return "rstudio"
    if page.locator(PositronSession.CONSOLE_PANEL).count() > 0:
        return "positron"
    if page.locator(VSCodeSession.WORKBENCH).count() > 0:
        return "vscode"
    return "unknown"


# ---------------------------------------------------------------------------
# Terminal execution (redirect + readback, no xterm widget scraping)
# ---------------------------------------------------------------------------


def _ensure_terminal_open(page: Page, timeout: int = 30_000) -> None:
    """Make the IDE's integrated terminal input visible before use.

    A freshly launched session does not start on the terminal: in RStudio the
    Console tab is selected and the Terminal tab's xterm widget is not rendered
    until the tab is activated; in VS Code/Positron no terminal panel exists
    until one is created. ``terminal_run`` therefore cannot assume
    ``.xterm-helper-textarea`` is already present. This helper is idempotent —
    it returns immediately when a terminal input is already visible.
    """
    terminal_input = page.locator(VSCodeSession.TERMINAL_INPUT)
    if terminal_input.count() > 0 and terminal_input.first.is_visible():
        return

    if page.locator(RStudioSession.CONTAINER).count() > 0:
        # RStudio: activate the Terminal tab in the console pane. Tab ids follow
        # #rstudio_workbench_tab_<name>; clicking creates a terminal on first open.
        term_tab = page.locator("#rstudio_workbench_tab_terminal")
        if term_tab.count() == 0:
            term_tab = page.get_by_role("tab", name=re.compile(r"\bTerminal\b"))
        if term_tab.count() > 0:
            term_tab.first.click()
    elif page.locator(VSCodeSession.WORKBENCH).count() > 0:
        # VS Code / Positron: open the integrated terminal (creates one if none).
        page.keyboard.press("Control+`")
    expect(terminal_input).to_be_visible(timeout=timeout)


def terminal_run(
    page: Page,
    cmd: str,
    timeout: int = 30_000,
    *,
    readback_lang: str = "r",
) -> str:
    """Run a shell command in the IDE terminal using redirect + readback.

    Redirects stdout/stderr to a unique temp file and appends a done marker
    to the file.  Polls for the done marker using a DOM-rendered console eval
    rather than scraping the xterm canvas/WebGL terminal widget.

    Strategy:
    1. Ensure the IDE terminal is open (activate the RStudio Terminal tab or
       create a VS Code/Positron terminal) so its input is present.
    2. Type ``{cmd} > {tmpfile} 2>&1; echo "VIP_DONE:$?" >> {tmpfile}`` in the
       terminal input (``.xterm-helper-textarea``).  The marker is appended
       with ``;`` rather than ``&&`` so it is always written, even when *cmd*
       fails -- see issue #439.
    3. Press Enter to execute.
    4. Poll for the done marker:
       - RStudio/Positron: call ``read_file`` (console eval, fresh each call).
       - VS Code: open the file once in the Monaco editor, then loop:
         read ``.view-lines``; if done_marker present → done; else close tab
         and re-open so the editor re-reads from disk.
    5. Once the marker appears, parse the exit code appended to it. A
       non-zero exit code raises ``ExecError`` immediately with the captured
       output, instead of waiting out the full timeout.

    Args:
        page: Playwright page for an active IDE session.
        cmd: Shell command to run.
        timeout: Max milliseconds to wait for completion.
        readback_lang: ``"r"`` (default) reads back via the R console;
            ``"python"`` reads back via the Python REPL.  Pass ``"python"``
            for pure VS Code sessions without Positron.

    Returns:
        Captured stdout/stderr of the command as a string.

    Raises:
        ExecError: *cmd* exited with a non-zero status (message includes the
            exit code and captured output), or the done marker never
            appeared within *timeout*.

    Note:
        The VS Code editor-open polling path is UNVALIDATED and pending a live
        git_ops run.  The open/close/re-read loop may be slow; it will be tuned
        during live validation.
    """
    done_marker = f"VIP_DONE_{uuid.uuid4().hex}"
    tmpfile = f"/tmp/vip_term_{uuid.uuid4().hex}.txt"
    shell_cmd = f'{cmd} > {tmpfile} 2>&1; echo "{done_marker}:$?" >> {tmpfile}'

    ide = _detect_ide(page)

    _ensure_terminal_open(page, timeout=timeout)
    terminal_input = page.locator(VSCodeSession.TERMINAL_INPUT)
    terminal_input.click()
    terminal_input.type(shell_cmd)
    terminal_input.press("Enter")

    deadline = time.monotonic() + timeout / 1000.0
    poll_interval = 1.0

    if ide == "vscode":
        # VS Code: poll by opening the file in the Monaco editor, reading
        # .view-lines, and closing+re-opening to force a disk re-read each poll.
        # NOTE: This path is UNVALIDATED pending a live git_ops run.
        while time.monotonic() < deadline:
            try:
                _open_file_in_vscode_editor(page, tmpfile, timeout=5_000)
                content = _read_vscode_editor_text(page, timeout=5_000)
                _close_active_editor(page)
                parsed = _parse_done_marker(content, done_marker)
                if parsed is not None:
                    output, exit_code = parsed
                    if exit_code != 0:
                        raise ExecError(
                            f"terminal_run: command {cmd!r} exited with status "
                            f"{exit_code}: {output}"
                        )
                    return output
            except ExecError:
                raise
            except Exception:
                pass
            time.sleep(poll_interval)
    else:
        # RStudio / Positron: poll via DOM console eval (read_file handles routing).
        while time.monotonic() < deadline:
            try:
                content = read_file(page, tmpfile, timeout=5_000, lang=readback_lang)
                parsed = _parse_done_marker(content, done_marker)
                if parsed is not None:
                    output, exit_code = parsed
                    if exit_code != 0:
                        raise ExecError(
                            f"terminal_run: command {cmd!r} exited with status "
                            f"{exit_code}: {output}"
                        )
                    return output
            except ExecError:
                raise
            except Exception:
                pass
            time.sleep(poll_interval)

    raise ExecError(
        f"terminal_run timed out after {timeout}ms waiting for done marker in {tmpfile!r}"
    )


# ---------------------------------------------------------------------------
# Filesystem readback
# ---------------------------------------------------------------------------


def file_exists(page: Page, path: str, timeout: int = 30_000, *, lang: str = "r") -> bool:
    """Check whether *path* exists on the Workbench server via a console expression.

    Auto-detects the IDE (RStudio, Positron, VS Code) and routes to the
    appropriate eval helper:
    - RStudio: R console via ``rstudio_eval``.
    - Positron: R or Python console via ``positron_eval_r`` / ``positron_eval_python``.
    - VS Code: runs a shell check via ``terminal_run`` (``[ -e path ]``) and
      inspects the output; no interpreter console is available.

    Args:
        page: Playwright page for an active IDE session.
        path: Server-side file path to check.
        timeout: Max milliseconds to wait for output.
        lang: ``"r"`` (default) or ``"python"``.  Ignored for VS Code (always
            uses the terminal).

    Returns:
        True if the file exists, False otherwise.
    """
    ide = _detect_ide(page)
    if ide == "positron":
        if lang.lower() == "r":
            result = positron_eval_r(page, f'file.exists("{path}")', timeout=timeout)
            return "TRUE" in result
        result = positron_eval_python(
            page, f'import os; print(os.path.exists("{path}"))', timeout=timeout
        )
        return "True" in result
    if ide == "vscode":
        # VS Code has no interpreter console: run the check via the terminal and
        # read the marker back via the editor-open path.
        # Use an ``if`` form so the redirect in terminal_run ({cmd} > tmpfile)
        # captures both branches. A bare ``A && B || C`` would bind the redirect
        # to ``C`` only, dropping VIP_EXISTS when the path exists.
        output = terminal_run(
            page,
            f"if [ -e {path} ]; then echo VIP_EXISTS; else echo VIP_MISSING; fi",
            timeout=timeout,
            readback_lang=lang,
        )
        return "VIP_EXISTS" in output
    # RStudio (and unknown — fall back to RStudio R path)
    if lang.lower() == "r":
        result = rstudio_eval(page, f'file.exists("{path}")', timeout=timeout)
        return "TRUE" in result
    result = rstudio_eval(page, f'file.exists("{path}")', timeout=timeout)
    return "TRUE" in result


def read_file(page: Page, path: str, timeout: int = 30_000, *, lang: str = "r") -> str:
    """Read the contents of *path* from the Workbench server via a console expression.

    Auto-detects the IDE (RStudio, Positron, VS Code) and routes to the
    appropriate eval helper:
    - RStudio: R console via ``rstudio_eval``.
    - Positron: R or Python console via ``positron_eval_r`` / ``positron_eval_python``.
    - VS Code: editor-open via ``read_file_via_vscode_editor`` — opens the file
      in Monaco and reads the rendered ``.view-lines`` text.

    Args:
        page: Playwright page for an active IDE session.
        path: Server-side file path to read.
        timeout: Max milliseconds to wait for output.
        lang: ``"r"`` (default) or ``"python"``.  Ignored for VS Code (always
            uses the editor-open path).

    Returns:
        File contents as a string.

    Raises:
        ExecError: If the expression output cannot be captured.
    """
    ide = _detect_ide(page)
    if ide == "positron":
        if lang.lower() == "r":
            expr = f'paste(readLines("{path}"), collapse="\\n")'
            return _strip_r_index(positron_eval_r(page, expr, timeout=timeout))
        return positron_eval_python(
            page, f'with open("{path}") as _f: print(_f.read())', timeout=timeout
        )
    if ide == "vscode":
        return read_file_via_vscode_editor(page, path, timeout=timeout)
    # RStudio (and unknown — fall back to RStudio R path)
    if lang.lower() == "r":
        expr = f'paste(readLines("{path}"), collapse="\\n")'
        return _strip_r_index(rstudio_eval(page, expr, timeout=timeout))
    expr = f'paste(readLines("{path}"), collapse="\\n")'
    return _strip_r_index(rstudio_eval(page, expr, timeout=timeout))
