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

from vip_tests.workbench.pages import (
    ConsolePaneSelectors,
    JupyterLabSession,
    PositronSession,
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


def _wrap_r_expr(expr: str, start: str, end: str) -> str:
    """Wrap *expr* in a semicolon-chained R statement fenced with VIP markers.

    Produces a single-line statement safe to type into the RStudio / Positron
    console input without triggering continuation prompts.

    Each sub-expression in a semicolon chain is auto-printed at the R REPL,
    so visible-valued expressions (e.g. ``1 + 1``, ``packageVersion('Matrix')``)
    print their result between the markers.

    Example output::

        cat("<<VIP-START-abc>>\\n"); 1 + 1; cat("\\n<<VIP-END-abc>>\\n")
    """
    return f'cat("{start}\\n"); {expr}; cat("\\n{end}\\n")'


def _wrap_python_expr(expr: str, start: str, end: str) -> str:
    """Wrap *expr* with Python print() markers.

    Returns a newline-separated block suitable for pasting into a JupyterLab
    cell or a Positron Python console as a single execution unit.

    Example output (3 lines)::

        print("<<VIP-START-abc>>")
        <expr>
        print("<<VIP-END-abc>>")
    """
    return f'print("{start}")\n{expr}\nprint("{end}")'


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
        ExecError: End marker did not appear within *timeout*, or the output
            cannot be parsed.
        PlaywrightTimeoutError: Console input was not visible within *timeout*.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_r_expr(expr, start, end)

    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    console_input.type(wrapped)
    console_input.press("Enter")

    console_output = page.locator(ConsolePaneSelectors.OUTPUT)
    expect(console_output).to_contain_text(end, timeout=timeout)

    text = console_output.text_content() or ""
    return _extract_between_markers(text, start, end)


def positron_eval_r(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as R in the Positron console and return the captured output.

    Uses the same marker-bracketed capture technique as ``rstudio_eval``.
    Targets the Positron-specific console panel (``.positron-console``).

    Args:
        page: Playwright page for an active Positron session.
        expr: R expression.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_r_expr(expr, start, end)

    console_panel = page.locator(PositronSession.CONSOLE_PANEL)
    expect(console_panel).to_be_visible(timeout=timeout)

    console_input = console_panel.locator(PositronSession.CONSOLE_INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    console_input.type(wrapped)
    console_input.press("Enter")

    expect(console_panel).to_contain_text(end, timeout=timeout)

    text = console_panel.text_content() or ""
    return _extract_between_markers(text, start, end)


def positron_eval_python(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as Python in the Positron console and return the captured output.

    Args:
        page: Playwright page for an active Positron session.
        expr: Python expression or statement.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_python_expr(expr, start, end)

    console_panel = page.locator(PositronSession.CONSOLE_PANEL)
    expect(console_panel).to_be_visible(timeout=timeout)

    console_input = console_panel.locator(PositronSession.CONSOLE_INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    # Submit each line separately; Enter inserts a newline in the console input
    for line in wrapped.splitlines():
        console_input.type(line)
        console_input.press("Enter")

    expect(console_panel).to_contain_text(end, timeout=timeout)

    text = console_panel.text_content() or ""
    return _extract_between_markers(text, start, end)


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


def vscode_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30_000) -> str:
    """Evaluate *expr* in VS Code via the Python or R extension REPL output panel.

    Uses the DOM-rendered output panel (Interactive Window for Python, R
    extension console for R) rather than the integrated terminal, ensuring
    reliable output capture without xterm canvas scraping.

    Args:
        page: Playwright page for an active VS Code session.
        expr: Code expression.
        lang: ``"python"`` (default) or ``"r"``.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    if lang.lower() == "r":
        wrapped = _wrap_r_expr(expr, start, end)
    else:
        wrapped = _wrap_python_expr(expr, start, end)

    repl_input = page.locator(VSCodeSession.REPL_INPUT)
    expect(repl_input).to_be_visible(timeout=timeout)
    repl_input.click()

    for line in wrapped.splitlines():
        repl_input.type(line)
        repl_input.press("Enter")

    repl_output = page.locator(VSCodeSession.REPL_OUTPUT)
    expect(repl_output).to_contain_text(end, timeout=timeout)

    text = repl_output.text_content() or ""
    return _extract_between_markers(text, start, end)


# ---------------------------------------------------------------------------
# Terminal execution (redirect + readback, no xterm widget scraping)
# ---------------------------------------------------------------------------


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
    1. Type ``{cmd} > {tmpfile} 2>&1 && echo VIP_DONE >> {tmpfile}`` in the
       terminal input (``.xterm-helper-textarea``).
    2. Press Enter to execute.
    3. Poll for the done marker by calling ``read_file`` (which uses
       ``rstudio_eval`` or ``vscode_eval`` depending on *readback_lang*).

    Args:
        page: Playwright page for an active IDE session.
        cmd: Shell command to run.
        timeout: Max milliseconds to wait for completion.
        readback_lang: ``"r"`` (default) reads back via the R console;
            ``"python"`` reads back via the Python REPL.  Pass ``"python"``
            for pure VS Code sessions without Positron.

    Returns:
        Captured stdout/stderr of the command as a string.
    """
    done_marker = f"VIP_DONE_{uuid.uuid4().hex}"
    tmpfile = f"/tmp/vip_term_{uuid.uuid4().hex}.txt"
    shell_cmd = f'{cmd} > {tmpfile} 2>&1 && echo "{done_marker}" >> {tmpfile}'

    terminal_input = page.locator(VSCodeSession.TERMINAL_INPUT)
    expect(terminal_input).to_be_visible(timeout=timeout)
    terminal_input.click()
    terminal_input.type(shell_cmd)
    terminal_input.press("Enter")

    # Poll for the done marker via DOM-rendered file readback
    deadline = time.monotonic() + timeout / 1000.0
    poll_interval = 1.0
    while time.monotonic() < deadline:
        try:
            content = read_file(page, tmpfile, timeout=5_000, lang=readback_lang)
            if done_marker in content:
                lines = [ln for ln in content.splitlines() if ln.strip() != done_marker]
                return "\n".join(lines).strip()
        except Exception:
            pass
        time.sleep(poll_interval)

    raise ExecError(
        f"terminal_run timed out after {timeout}ms waiting for done marker in {tmpfile!r}"
    )


# ---------------------------------------------------------------------------
# Filesystem readback
# ---------------------------------------------------------------------------


def file_exists(
    page: Page, path: str, timeout: int = 30_000, *, lang: str = "r"
) -> bool:
    """Check whether *path* exists on the Workbench server via a console expression.

    Uses ``rstudio_eval`` (R) or ``vscode_eval`` (Python) to run a file-check
    expression in a DOM-rendered console, avoiding any filesystem access from
    the Playwright process.

    Args:
        page: Playwright page for an active IDE session.
        path: Server-side file path to check.
        timeout: Max milliseconds to wait for output.
        lang: ``"r"`` (default) or ``"python"``.

    Returns:
        True if the file exists, False otherwise.
    """
    if lang.lower() == "r":
        result = rstudio_eval(page, f'file.exists("{path}")', timeout=timeout)
        return "TRUE" in result
    else:
        result = vscode_eval(page, f'import os; print(os.path.exists("{path}"))', timeout=timeout)
        return "True" in result


def read_file(
    page: Page, path: str, timeout: int = 30_000, *, lang: str = "r"
) -> str:
    """Read the contents of *path* from the Workbench server via a console expression.

    Uses ``rstudio_eval`` (R) or ``vscode_eval`` (Python) to run a file-read
    expression in a DOM-rendered console.

    Args:
        page: Playwright page for an active IDE session.
        path: Server-side file path to read.
        timeout: Max milliseconds to wait for output.
        lang: ``"r"`` (default) or ``"python"``.

    Returns:
        File contents as a string.

    Raises:
        ExecError: If the expression output cannot be captured.
    """
    if lang.lower() == "r":
        expr = f'paste(readLines("{path}"), collapse="\\n")'
        result = rstudio_eval(page, expr, timeout=timeout)
        return _strip_r_index(result)
    else:
        result = vscode_eval(
            page,
            f'with open("{path}") as _f: print(_f.read())',
            timeout=timeout,
        )
        return result


def _wrap_python_expr(expr: str, start: str, end: str) -> str:
    """Wrap *expr* with Python print() markers.

    Returns a newline-separated block suitable for pasting into a JupyterLab
    cell or a Positron Python console as a single execution unit.
    """
    return f'print("{start}")\n{expr}\nprint("{end}")'


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

    Example::

        >>> _strip_r_index("[1] 1.0.6")
        '1.0.6'
        >>> _strip_r_index("[1] \\"Matrix\\"\\n[2] \\"methods\\"")
        '\\"Matrix\\"\\n\\"methods\\"'
    """
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"^\[\d+\]\s*", "", line) if re.match(r"^\[\d+\]", line) else line)
    return "\n".join(lines).strip()


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
        ExecError: End marker did not appear within *timeout*, or the output
            cannot be parsed.
        PlaywrightTimeoutError: Console input was not visible within *timeout*.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_r_expr(expr, start, end)

    console_input = page.locator(ConsolePaneSelectors.INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    console_input.type(wrapped)
    console_input.press("Enter")

    console_output = page.locator(ConsolePaneSelectors.OUTPUT)
    expect(console_output).to_contain_text(end, timeout=timeout)

    text = console_output.text_content() or ""
    return _extract_between_markers(text, start, end)


def positron_eval_r(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as R in the Positron console and return the captured output.

    Uses the same marker-bracketed capture technique as ``rstudio_eval``.
    Targets the Positron-specific console panel (``.positron-console``).

    Args:
        page: Playwright page for an active Positron session.
        expr: R expression.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_r_expr(expr, start, end)

    console_panel = page.locator(PositronSession.CONSOLE_PANEL)
    expect(console_panel).to_be_visible(timeout=timeout)

    console_input = console_panel.locator(PositronSession.CONSOLE_INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    console_input.type(wrapped)
    console_input.press("Enter")

    expect(console_panel).to_contain_text(end, timeout=timeout)

    text = console_panel.text_content() or ""
    return _extract_between_markers(text, start, end)


def positron_eval_python(page: Page, expr: str, timeout: int = 30_000) -> str:
    """Evaluate *expr* as Python in the Positron console and return the captured output.

    Args:
        page: Playwright page for an active Positron session.
        expr: Python expression or statement.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    start, end = _make_sentinels()
    wrapped = _wrap_python_expr(expr, start, end)

    console_panel = page.locator(PositronSession.CONSOLE_PANEL)
    expect(console_panel).to_be_visible(timeout=timeout)

    console_input = console_panel.locator(PositronSession.CONSOLE_INPUT)
    expect(console_input).to_be_visible(timeout=timeout)
    console_input.click()
    # Python blocks require each line to be submitted; type and run line-by-line
    for line in wrapped.splitlines():
        console_input.type(line)
        console_input.press("Enter")

    expect(console_panel).to_contain_text(end, timeout=timeout)

    text = console_panel.text_content() or ""
    return _extract_between_markers(text, start, end)


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

    if lang.lower() == "python":
        for line in wrapped.splitlines():
            cell_input.type(line)
            cell_input.press("Enter")
        # Remove the trailing Enter that would immediately execute; we use Shift+Enter below
    else:
        cell_input.type(wrapped)

    cell_input.press("Shift+Enter")

    cell_output = page.locator(JupyterLabSession.CELL_OUTPUT).last
    expect(cell_output).to_contain_text(end, timeout=timeout)

    text = cell_output.text_content() or ""
    return _extract_between_markers(text, start, end)


def vscode_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30_000) -> str:
    """Evaluate *expr* in VS Code via the Python or R extension REPL output panel.

    Uses the DOM-rendered output panel (Interactive Window for Python, R
    extension console for R) rather than the integrated terminal, ensuring
    reliable output capture without xterm canvas scraping.

    Args:
        page: Playwright page for an active VS Code session.
        expr: Code expression.
        lang: ``"python"`` (default) or ``"r"``.
        timeout: Max milliseconds to wait for output.

    Returns:
        Raw text between the VIP markers, stripped of whitespace.
    """
    from vip_tests.workbench.pages.vscode_session import VSCodeSession

    start, end = _make_sentinels()
    if lang.lower() == "r":
        wrapped = _wrap_r_expr(expr, start, end)
    else:
        wrapped = _wrap_python_expr(expr, start, end)

    repl_input = page.locator(VSCodeSession.REPL_INPUT)
    expect(repl_input).to_be_visible(timeout=timeout)
    repl_input.click()

    for line in wrapped.splitlines():
        repl_input.type(line)
        repl_input.press("Enter")

    repl_output = page.locator(VSCodeSession.REPL_OUTPUT)
    expect(repl_output).to_contain_text(end, timeout=timeout)

    text = repl_output.text_content() or ""
    return _extract_between_markers(text, start, end)


# ---------------------------------------------------------------------------
# Terminal execution (redirect + readback, no xterm widget scraping)
# ---------------------------------------------------------------------------


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
    1. Type ``{cmd} > {tmpfile} 2>&1 && echo VIP_DONE >> {tmpfile}`` in the
       terminal input (``.xterm-helper-textarea``).
    2. Press Enter to execute.
    3. Poll for the done marker by calling ``read_file`` (which uses
       ``rstudio_eval`` or ``vscode_eval`` depending on *readback_lang*).

    Args:
        page: Playwright page for an active IDE session.
        cmd: Shell command to run.
        timeout: Max milliseconds to wait for completion.
        readback_lang: ``"r"`` (default) reads back via the R console;
            ``"python"`` reads back via the Python REPL.  Pass ``"python"``
            for pure VS Code sessions without Positron.

    Returns:
        Captured stdout/stderr of the command as a string.
    """
    from vip_tests.workbench.pages.vscode_session import VSCodeSession

    done_marker = f"VIP_DONE_{uuid.uuid4().hex}"
    tmpfile = f"/tmp/vip_term_{uuid.uuid4().hex}.txt"
    shell_cmd = f'{cmd} > {tmpfile} 2>&1 && echo "{done_marker}" >> {tmpfile}'

    terminal_input = page.locator(VSCodeSession.TERMINAL_INPUT)
    expect(terminal_input).to_be_visible(timeout=timeout)
    terminal_input.click()
    terminal_input.type(shell_cmd)
    terminal_input.press("Enter")

    # Poll for the done marker via DOM-rendered file readback
    import time

    deadline = time.monotonic() + timeout / 1000.0
    poll_interval = 1.0
    while time.monotonic() < deadline:
        try:
            content = read_file(page, tmpfile, timeout=5_000, lang=readback_lang)
            if done_marker in content:
                # Strip the done marker line before returning
                lines = [ln for ln in content.splitlines() if ln.strip() != done_marker]
                return "\n".join(lines).strip()
        except (ExecError, Exception):
            pass
        time.sleep(poll_interval)

    raise ExecError(
        f"terminal_run timed out after {timeout}ms waiting for done marker in {tmpfile!r}"
    )


# ---------------------------------------------------------------------------
# Filesystem readback
# ---------------------------------------------------------------------------


def file_exists(
    page: Page, path: str, timeout: int = 30_000, *, lang: str = "r"
) -> bool:
    """Check whether *path* exists on the Workbench server via a console expression.

    Uses ``rstudio_eval`` (R) or ``vscode_eval`` (Python) to run a file-check
    expression in a DOM-rendered console, avoiding any filesystem access from
    the Playwright process.

    Args:
        page: Playwright page for an active IDE session.
        path: Server-side file path to check.
        timeout: Max milliseconds to wait for output.
        lang: ``"r"`` (default) or ``"python"``.

    Returns:
        True if the file exists, False otherwise.
    """
    if lang.lower() == "r":
        result = rstudio_eval(page, f'file.exists("{path}")', timeout=timeout)
        return "TRUE" in result
    else:
        result = vscode_eval(page, f'import os; print(os.path.exists("{path}"))', timeout=timeout)
        return "True" in result


def read_file(
    page: Page, path: str, timeout: int = 30_000, *, lang: str = "r"
) -> str:
    """Read the contents of *path* from the Workbench server via a console expression.

    Uses ``rstudio_eval`` (R) or ``vscode_eval`` (Python) to run a file-read
    expression in a DOM-rendered console.

    Args:
        page: Playwright page for an active IDE session.
        path: Server-side file path to read.
        timeout: Max milliseconds to wait for output.
        lang: ``"r"`` (default) or ``"python"``.

    Returns:
        File contents as a string.

    Raises:
        ExecError: If the expression output cannot be captured.
    """
    if lang.lower() == "r":
        expr = f'paste(readLines("{path}"), collapse="\\n")'
        result = rstudio_eval(page, expr, timeout=timeout)
        return _strip_r_index(result)
    else:
        result = vscode_eval(
            page,
            f'with open("{path}") as _f: print(_f.read())',
            timeout=timeout,
        )
        return result
