"""Selftests for the workbench.exec pure-logic helpers.

These tests cover the deterministic, Playwright-free functions extracted from
``src/vip_tests/workbench/exec.py``:

- ``_wrap_r_expr`` / ``_wrap_python_expr`` — marker-bracketed expression fencing
- ``_extract_between_markers`` — output extraction between UUID sentinels
- ``_strip_r_index`` — R vector-index prefix stripping
- ``_make_sentinels`` — UUID sentinel format validation
- ``_detect_ide`` — IDE detection from page DOM selectors
- Routing in ``file_exists`` and ``read_file`` per detected IDE
- Error-path behavior (missing start/end markers)

No live Workbench deployment or Playwright browser is required.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

import vip_tests.workbench.exec as exec_mod
from vip_tests.workbench.exec import (
    ExecError,
    _detect_ide,
    _extract_between_markers,
    _make_sentinels,
    _parse_done_marker,
    _read_file_r_expr,
    _split_marker,
    _strip_r_index,
    _wrap_python_expr,
    _wrap_r_expr,
    ensure_positron_console,
    file_exists,
    read_file,
)
from vip_tests.workbench.pages import PositronSession, RStudioSession, VSCodeSession

# ---------------------------------------------------------------------------
# _make_sentinels
# ---------------------------------------------------------------------------


class TestMakeSentinels:
    def test_returns_two_strings(self):
        start, end = _make_sentinels()
        assert isinstance(start, str)
        assert isinstance(end, str)

    def test_start_has_vip_start_prefix(self):
        start, _ = _make_sentinels()
        assert start.startswith("<<VIP-START-")
        assert start.endswith(">>")

    def test_end_has_vip_end_prefix(self):
        _, end = _make_sentinels()
        assert end.startswith("<<VIP-END-")
        assert end.endswith(">>")

    def test_unique_per_call(self):
        s1, e1 = _make_sentinels()
        s2, e2 = _make_sentinels()
        assert s1 != s2
        assert e1 != e2

    def test_hex_uid_in_sentinel(self):
        start, end = _make_sentinels()
        # extract the uid portion: <<VIP-START-{uid}>>
        uid_from_start = start[len("<<VIP-START-") : -2]
        uid_from_end = end[len("<<VIP-END-") : -2]
        assert uid_from_start == uid_from_end, "start and end should share the same UUID"
        # uid must be a 32-char hex string (uuid4.hex)
        assert re.fullmatch(r"[0-9a-f]{32}", uid_from_start), (
            f"expected 32-char hex, got {uid_from_start!r}"
        )


# ---------------------------------------------------------------------------
# _wrap_r_expr
# ---------------------------------------------------------------------------


class TestWrapRExpr:
    def test_full_marker_not_contiguous_in_source(self):
        """The full marker must NOT appear contiguously in the typed source.

        Consoles echo typed input back into the same pane we read output from.
        If the literal marker appeared in the echo, the readiness wait and
        ``_extract_between_markers`` would match the echoed command instead of
        its output (the regression that captured ``'\\n"); 1 + 1; cat("\\n'``).
        """
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_r_expr("1 + 1", start, end)
        assert start not in result
        assert end not in result

    def test_marker_halves_present(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_r_expr("1 + 1", start, end)
        for half in (*_split_marker(start), *_split_marker(end)):
            assert half in result

    def test_contains_expression(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        expr = "Sys.time()"
        result = _wrap_r_expr(expr, start, end)
        assert expr in result

    def test_single_line_output(self):
        """Wrapped expression must not span multiple unbalanced lines.

        The RStudio console input is a single-line widget; the result should
        be expressible as a semicolon-chained statement (no raw newlines that
        would prematurely submit the expression).
        """
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_r_expr("1 + 1", start, end)
        # Must contain no unescaped newlines outside of string literals
        # (the escaped \n inside the cat strings is fine and expected)
        assert "\n" not in result

    def test_markers_wrap_expression(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_r_expr("1 + 1", start, end)
        # Start marker (first half) should appear before the expression, which
        # in turn appears before the end marker.
        s1, _ = _split_marker(start)
        e1, _ = _split_marker(end)
        assert result.index(s1) < result.index("1 + 1") < result.index(e1)

    def test_double_quotes_in_expr_inline(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        expr = 'print("hello")'
        result = _wrap_r_expr(expr, start, end)
        # Expression is inlined as-is (no escaping); double quotes appear in the result
        assert expr in result


# ---------------------------------------------------------------------------
# _wrap_python_expr
# ---------------------------------------------------------------------------


class TestWrapPythonExpr:
    def test_full_marker_not_contiguous_in_source(self):
        """The full marker must NOT appear contiguously in the typed source.

        The Positron Python console echoes typed input; splitting the marker
        keeps the readiness wait and extraction keyed to the printed output.
        """
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("1 + 1", start, end)
        assert start not in result
        assert end not in result

    def test_marker_halves_present(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("1 + 1", start, end)
        for half in (*_split_marker(start), *_split_marker(end)):
            assert half in result

    def test_contains_expression(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        expr = "import sys; print(sys.version)"
        result = _wrap_python_expr(expr, start, end)
        assert expr in result

    def test_multiline_block(self):
        """Python wrapping is newline-separated (suitable for cell/paste input)."""
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("print('hi')", start, end)
        lines = result.splitlines()
        assert len(lines) >= 3, "Expected at least 3 lines: start-print, expr, end-print"

    def test_start_print_is_first_line(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("x = 1", start, end)
        first_line = result.splitlines()[0]
        assert _split_marker(start)[0] in first_line

    def test_end_print_is_last_line(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("x = 1", start, end)
        last_line = result.splitlines()[-1]
        assert _split_marker(end)[0] in last_line


# ---------------------------------------------------------------------------
# _extract_between_markers
# ---------------------------------------------------------------------------


class TestExtractBetweenMarkers:
    def test_basic_extraction(self):
        start, end = "<<S>>", "<<E>>"
        text = "garbage<<S>>\nhello world\n<<E>>more garbage"
        assert _extract_between_markers(text, start, end) == "hello world"

    def test_strips_surrounding_whitespace(self):
        start, end = "<<S>>", "<<E>>"
        text = "<<S>>  \n  value  \n  <<E>>"
        assert _extract_between_markers(text, start, end) == "value"

    def test_empty_content_between_markers(self):
        start, end = "<<S>>", "<<E>>"
        text = "<<S>><<E>>"
        assert _extract_between_markers(text, start, end) == ""

    def test_multi_line_content(self):
        start, end = "<<S>>", "<<E>>"
        text = "<<S>>\nline 1\nline 2\n<<E>>"
        result = _extract_between_markers(text, start, end)
        assert "line 1" in result
        assert "line 2" in result

    def test_raises_on_missing_start_marker(self):
        with pytest.raises(ExecError, match="Start marker"):
            _extract_between_markers("no markers here", "<<S>>", "<<E>>")

    def test_raises_on_missing_end_marker(self):
        with pytest.raises(ExecError, match="End marker"):
            _extract_between_markers("<<S>>content but no end", "<<S>>", "<<E>>")

    def test_uses_first_start_marker(self):
        """When start marker appears twice, extraction uses the first occurrence."""
        start, end = "<<S>>", "<<E>>"
        text = "<<S>>first<<E>>noise<<S>>second<<E>>"
        result = _extract_between_markers(text, start, end)
        assert result == "first"

    def test_full_round_trip_r(self):
        """Simulates the pane: the echoed command followed by the real output.

        Regression guard: because the wrapped command's markers are split, the
        echoed input must NOT contain a full contiguous marker, so extraction
        keys off the executed output (``[1] 2``) rather than the echo.
        """
        start, end = _make_sentinels()
        wrapped = _wrap_r_expr("1 + 1", start, end)
        # Echo of the typed command, then the executed output between markers.
        simulated_output = f"> {wrapped}\n{start}\n[1] 2\n{end}\n> "
        result = _extract_between_markers(simulated_output, start, end)
        assert result == "[1] 2"

    def test_full_round_trip_python(self):
        """Simulates what the cell output would contain for a Python eval."""
        start, end = _make_sentinels()
        simulated_output = f"{start}\n42\n{end}"
        result = _extract_between_markers(simulated_output, start, end)
        assert result == "42"


# ---------------------------------------------------------------------------
# _strip_r_index
# ---------------------------------------------------------------------------


class TestStripRIndex:
    def test_strips_single_index(self):
        assert _strip_r_index("[1] 1.0.6") == "1.0.6"

    def test_strips_multi_digit_index(self):
        assert _strip_r_index("[12] value") == "value"

    def test_strips_multiple_lines(self):
        text = "[1] alpha\n[2] beta"
        result = _strip_r_index(text)
        assert result == "alpha\nbeta"

    def test_preserves_lines_without_index(self):
        text = "no index here\n[1] has index"
        result = _strip_r_index(text)
        assert "no index here" in result
        assert "has index" in result
        assert "[1]" not in result

    def test_empty_string(self):
        assert _strip_r_index("") == ""

    def test_no_indices_returns_unchanged(self):
        text = "hello world"
        assert _strip_r_index(text) == "hello world"

    def test_quoted_string_result(self):
        """R often quotes strings: [1] \"Matrix\" → \"Matrix\"."""
        text = '[1] "Matrix"'
        result = _strip_r_index(text)
        assert result == '"Matrix"'

    def test_strips_whitespace_after_index(self):
        """There should be no leading space after the index is removed."""
        result = _strip_r_index("[1] value")
        assert not result.startswith(" ")


# ---------------------------------------------------------------------------
# _parse_done_marker
# ---------------------------------------------------------------------------


class TestParseDoneMarker:
    def test_returns_none_when_marker_absent(self):
        """Command still running: no marker line yet, regardless of content."""
        assert _parse_done_marker("some partial output", "VIP_DONE_abc") is None

    def test_parses_success_exit_code(self):
        content = "hello\nworld\nVIP_DONE_abc:0"
        result = _parse_done_marker(content, "VIP_DONE_abc")
        assert result == ("hello\nworld", 0)

    def test_parses_nonzero_exit_code(self):
        """Regression guard for #439: marker is now written even on failure."""
        content = "fatal: destination path 'x' already exists\nVIP_DONE_abc:128"
        result = _parse_done_marker(content, "VIP_DONE_abc")
        assert result == ("fatal: destination path 'x' already exists", 128)

    def test_marker_line_removed_from_output(self):
        content = "line1\nVIP_DONE_abc:1\nline2"
        output, exit_code = _parse_done_marker(content, "VIP_DONE_abc")
        assert "VIP_DONE_abc" not in output
        assert "line1" in output
        assert "line2" in output
        assert exit_code == 1

    def test_empty_output_between_marker(self):
        content = "VIP_DONE_abc:0"
        assert _parse_done_marker(content, "VIP_DONE_abc") == ("", 0)

    def test_does_not_match_different_marker(self):
        """A different run's marker must not be mistaken for this one."""
        content = "output\nVIP_DONE_other:0"
        assert _parse_done_marker(content, "VIP_DONE_abc") is None

    def test_marker_glued_to_output_with_no_trailing_newline(self):
        """cmd's last line lacking a trailing newline glues the marker onto
        it (`>>` appends raw bytes with no separator); the glued-on leading
        text is real output and must be kept, not dropped."""
        content = "foobar" + "VIP_DONE_abc:0"
        assert _parse_done_marker(content, "VIP_DONE_abc") == ("foobar", 0)

    def test_returns_none_for_non_digit_suffix(self):
        """A marker line whose exit-code suffix isn't purely digits yet (a
        partial write mid-poll) must be treated as still-running, not raise."""
        content = "VIP_DONE_abc:"
        assert _parse_done_marker(content, "VIP_DONE_abc") is None

    def test_raw_exit_code_parses_but_quoted_does_not(self):
        """Regression guard: R's auto-print wraps a bare (un-cat'd) character
        result in a trailing closing quote, turning ``...:0`` into ``...:0"``.
        The raw form must parse as exit 0; the quoted form must be treated as
        still-running rather than silently misparsed. This is why
        ``_read_file_r_expr`` wraps its read expression in ``cat()`` -- so the
        marker line R's console echoes back is always the raw form."""
        raw = "hello\nVIP_DONE_abc:0"
        quoted = 'hello\nVIP_DONE_abc:0"'
        assert _parse_done_marker(raw, "VIP_DONE_abc") == ("hello", 0)
        assert _parse_done_marker(quoted, "VIP_DONE_abc") is None


# ---------------------------------------------------------------------------
# _read_file_r_expr
# ---------------------------------------------------------------------------


class TestReadFileRExpr:
    def test_wraps_read_in_cat(self):
        """The read expression must be cat()'d, not left as a bare/auto-printed
        expression -- R's console auto-print wraps a bare character result in
        quotes and escapes embedded newlines as literal ``\\n``, which broke
        the done-marker exit-code parse (see TestParseDoneMarker above)."""
        expr = _read_file_r_expr("/tmp/foo.txt")
        assert expr.startswith("cat(")
        assert "readLines(" in expr
        assert "paste(" in expr

    def test_embeds_path(self):
        expr = _read_file_r_expr("/tmp/vip_term_abc.txt")
        assert '"/tmp/vip_term_abc.txt"' in expr


# ---------------------------------------------------------------------------
# _detect_ide
# ---------------------------------------------------------------------------


def _make_page_mock(present_selectors: set[str]) -> MagicMock:
    """Return a MagicMock page whose locator().count() reflects *present_selectors*.

    Any selector in *present_selectors* returns count() == 1; others return 0.
    """
    page = MagicMock()

    def locator_side_effect(selector):
        loc = MagicMock()
        loc.count.return_value = 1 if selector in present_selectors else 0
        return loc

    page.locator.side_effect = locator_side_effect
    return page


class TestDetectIde:
    def test_rstudio_detected(self):
        page = _make_page_mock({RStudioSession.CONTAINER})
        assert _detect_ide(page) == "rstudio"

    def test_positron_detected_even_with_monaco(self):
        """Positron renders .monaco-workbench AND .positron-console; must win over vscode."""
        page = _make_page_mock({PositronSession.CONSOLE_PANEL, VSCodeSession.WORKBENCH})
        assert _detect_ide(page) == "positron"

    def test_positron_detected_via_variables_pane_without_console(self):
        """Positron opens without an auto-started console (issue #477): the console
        panel is absent on the Welcome page, but ``.positron-variables`` is always
        present, so detection must not depend on a running console."""
        page = _make_page_mock({PositronSession.VARIABLES_PANE, VSCodeSession.WORKBENCH})
        assert _detect_ide(page) == "positron"

    def test_vscode_detected_without_positron_console(self):
        page = _make_page_mock({VSCodeSession.WORKBENCH})
        assert _detect_ide(page) == "vscode"

    def test_unknown_when_nothing_present(self):
        page = _make_page_mock(set())
        assert _detect_ide(page) == "unknown"


# ---------------------------------------------------------------------------
# ensure_positron_console
# ---------------------------------------------------------------------------


class _FakeKeyboard:
    def __init__(self, raises=False):
        self.pressed: list[str] = []
        self._raises = raises

    def press(self, key):
        if self._raises:
            raise RuntimeError("keyboard detached")
        self.pressed.append(key)


class _EnsureFakeLocator:
    """Locator whose count()/click() reflect the parent fake page's state."""

    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    @property
    def first(self):
        return self

    def count(self):
        p = self._page
        if self._selector == PositronSession.CONSOLE_PANEL:
            if p.has_console_panel:
                return 1
            return 1 if (p.interpreter_selected and p.console_renders) else 0
        if self._selector == PositronSession.START_CONSOLE_BUTTON:
            return 1 if p.has_start_button else 0
        if self._selector == PositronSession.INTERPRETER_QUICKPICK_ROW:
            if p.quickpick_after is None:
                return 0
            return 1 if p.polls >= p.quickpick_after else 0
        return 0

    def click(self, timeout=None):
        if self._selector == PositronSession.START_CONSOLE_BUTTON:
            self._page.start_clicked += 1
        elif self._selector == PositronSession.INTERPRETER_QUICKPICK_ROW:
            if self._page.row_click_raises:
                raise RuntimeError("row detached")
            self._page.rows_clicked += 1
            self._page.interpreter_selected = True


class _EnsureFakePage:
    """Scriptable fake Positron page for ensure_positron_console tests.

    - ``has_console_panel``: a console is already running.
    - ``has_start_button``: the "Start New Console Session" button is present.
    - ``quickpick_after``: number of poll cycles before the interpreter quickpick
      populates (``None`` = never, i.e. no interpreter resolves).
    - ``console_renders``: whether the console appears after selecting an interpreter.
    """

    def __init__(
        self,
        *,
        has_console_panel=False,
        has_start_button=True,
        quickpick_after=0,
        console_renders=True,
        row_click_raises=False,
        keyboard_raises=False,
    ):
        self.has_console_panel = has_console_panel
        self.has_start_button = has_start_button
        self.quickpick_after = quickpick_after
        self.console_renders = console_renders
        self.row_click_raises = row_click_raises
        self.polls = 0
        self.interpreter_selected = False
        self.start_clicked = 0
        self.rows_clicked = 0
        self.keyboard = _FakeKeyboard(raises=keyboard_raises)

    def locator(self, selector):
        return _EnsureFakeLocator(self, selector)

    def wait_for_timeout(self, ms):
        self.polls += 1


class TestEnsurePositronConsole:
    def test_returns_true_without_clicking_when_console_already_running(self):
        page = _EnsureFakePage(has_console_panel=True)
        assert ensure_positron_console(page) is True
        assert page.start_clicked == 0

    def test_returns_false_when_no_start_button(self):
        page = _EnsureFakePage(has_console_panel=False, has_start_button=False)
        assert ensure_positron_console(page) is False

    def test_starts_console_when_quickpick_populates_asynchronously(self):
        """Interpreter discovery lags the Start click (~10s live). ensure must
        poll the quickpick, then select an interpreter and confirm the console."""
        page = _EnsureFakePage(quickpick_after=2, console_renders=True)
        assert ensure_positron_console(page, timeout=10_000) is True
        assert page.start_clicked == 1
        assert page.rows_clicked == 1
        assert page.interpreter_selected is True

    def test_returns_false_when_no_interpreter_resolves(self):
        """Genuinely no interpreter available: quickpick never populates → False
        (caller decides on an accurate skip, not a misleading 'not installed')."""
        page = _EnsureFakePage(quickpick_after=None)
        assert ensure_positron_console(page, timeout=3_000) is False
        assert page.rows_clicked == 0

    def test_returns_false_when_console_never_renders_after_select(self):
        page = _EnsureFakePage(quickpick_after=0, console_renders=False)
        assert ensure_positron_console(page, timeout=3_000) is False
        assert page.interpreter_selected is True

    def test_never_raises_when_both_row_click_and_enter_fail(self):
        """Honour the "never raises" contract: if selecting the interpreter row
        fails AND the Enter keyboard fallback also raises, return False."""
        page = _EnsureFakePage(
            quickpick_after=0,
            console_renders=False,
            row_click_raises=True,
            keyboard_raises=True,
        )
        assert ensure_positron_console(page, timeout=2_000) is False

    def test_total_wait_bounded_by_timeout(self):
        """The poll budget is SHARED across discovery + render, so total waits
        never exceed ~timeout (not ~2x). Interpreter resolves after 2 polls but
        the console never renders; with timeout=5000ms / 1000ms poll the total
        wait cycles must stay <= 5 (a per-loop budget would allow ~7)."""
        page = _EnsureFakePage(quickpick_after=2, console_renders=False)
        assert ensure_positron_console(page, timeout=5_000) is False
        assert page.polls <= 5


# ---------------------------------------------------------------------------
# Routing in file_exists
# ---------------------------------------------------------------------------


class TestFileExistsRouting:
    def test_rstudio_calls_rstudio_eval(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "rstudio")
        mock_rstudio_eval = MagicMock(return_value="TRUE")
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = file_exists(page, "/tmp/foo.txt", lang="r")

        assert result is True
        mock_rstudio_eval.assert_called_once()
        mock_positron_eval_r.assert_not_called()
        mock_positron_eval_python.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_positron_r_calls_positron_eval_r(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "positron")
        mock_rstudio_eval = MagicMock()
        mock_positron_eval_r = MagicMock(return_value="TRUE")
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = file_exists(page, "/tmp/foo.txt", lang="r")

        assert result is True
        mock_positron_eval_r.assert_called_once()
        mock_rstudio_eval.assert_not_called()
        mock_positron_eval_python.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_positron_python_calls_positron_eval_python(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "positron")
        mock_rstudio_eval = MagicMock()
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock(return_value="True")
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = file_exists(page, "/tmp/foo.txt", lang="python")

        assert result is True
        mock_positron_eval_python.assert_called_once()
        mock_rstudio_eval.assert_not_called()
        mock_positron_eval_r.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_vscode_uses_terminal_run(self, monkeypatch):
        """VS Code file_exists routes through terminal_run (no console eval)."""
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "vscode")
        mock_rstudio_eval = MagicMock()
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        mock_terminal_run = MagicMock(return_value="VIP_EXISTS")
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)
        monkeypatch.setattr(exec_mod, "terminal_run", mock_terminal_run)

        result = file_exists(page, "/tmp/foo.txt", lang="python")

        assert result is True
        mock_terminal_run.assert_called_once()
        mock_rstudio_eval.assert_not_called()
        mock_positron_eval_r.assert_not_called()
        mock_positron_eval_python.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_vscode_returns_false_when_missing(self, monkeypatch):
        """VS Code file_exists returns False when VIP_MISSING is in terminal output."""
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "vscode")
        mock_terminal_run = MagicMock(return_value="VIP_MISSING")
        monkeypatch.setattr(exec_mod, "terminal_run", mock_terminal_run)

        result = file_exists(page, "/tmp/nonexistent.txt", lang="python")

        assert result is False


# ---------------------------------------------------------------------------
# Routing in read_file
# ---------------------------------------------------------------------------


class TestReadFileRouting:
    def test_rstudio_calls_rstudio_eval(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "rstudio")
        # cat()'d output is raw -- no "[1]" index, no quoting -- so the mock
        # return value here is the *raw* form, not R's auto-printed form.
        mock_rstudio_eval = MagicMock(return_value="hello world")
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = read_file(page, "/tmp/foo.txt", lang="r")

        assert result == "hello world"
        rstudio_expr = mock_rstudio_eval.call_args[0][1]
        assert rstudio_expr.startswith("cat(")  # not a bare auto-printed expr
        mock_rstudio_eval.assert_called_once()
        mock_positron_eval_r.assert_not_called()
        mock_positron_eval_python.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_positron_r_calls_positron_eval_r(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "positron")
        mock_rstudio_eval = MagicMock()
        # cat()'d output is raw -- no "[1]" index, no quoting.
        mock_positron_eval_r = MagicMock(return_value="file contents")
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = read_file(page, "/tmp/foo.txt", lang="r")

        assert result == "file contents"
        positron_expr = mock_positron_eval_r.call_args[0][1]
        assert positron_expr.startswith("cat(")  # not a bare auto-printed expr
        mock_positron_eval_r.assert_called_once()
        mock_rstudio_eval.assert_not_called()
        mock_positron_eval_python.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_positron_python_calls_positron_eval_python(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "positron")
        mock_rstudio_eval = MagicMock()
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock(return_value="python file contents")
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = read_file(page, "/tmp/foo.txt", lang="python")

        assert result == "python file contents"
        mock_positron_eval_python.assert_called_once()
        mock_rstudio_eval.assert_not_called()
        mock_positron_eval_r.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_vscode_calls_editor_read(self, monkeypatch):
        """VS Code read_file routes to read_file_via_vscode_editor (no console eval)."""
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "vscode")
        mock_rstudio_eval = MagicMock()
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock(return_value="vscode file contents")
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = read_file(page, "/tmp/foo.txt", lang="python")

        assert result == "vscode file contents"
        mock_editor_read.assert_called_once()
        mock_rstudio_eval.assert_not_called()
        mock_positron_eval_r.assert_not_called()
        mock_positron_eval_python.assert_not_called()

    def test_vscode_read_ignores_lang_parameter(self, monkeypatch):
        """VS Code read_file uses editor-open regardless of lang."""
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "vscode")
        mock_editor_read = MagicMock(return_value="editor contents")
        mock_rstudio_eval = MagicMock()
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)

        result_r = read_file(page, "/tmp/foo.txt", lang="r")
        result_py = read_file(page, "/tmp/foo.txt", lang="python")

        assert result_r == "editor contents"
        assert result_py == "editor contents"
        assert mock_editor_read.call_count == 2
        mock_rstudio_eval.assert_not_called()


# ---------------------------------------------------------------------------
# terminal_run
# ---------------------------------------------------------------------------


class _FixedUUID:
    hex = "deadbeef"


class TestTerminalRun:
    """Regression coverage for #439: fast-failing commands must raise
    ExecError immediately with the real output, not a generic timeout."""

    def _patch_common(self, monkeypatch, ide="rstudio"):
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: ide)
        monkeypatch.setattr(exec_mod, "_ensure_terminal_open", lambda p, timeout=30_000: None)
        monkeypatch.setattr(exec_mod.uuid, "uuid4", lambda: _FixedUUID())

    def test_writes_done_marker_unconditionally(self, monkeypatch):
        """The marker must be appended with ``;`` so it is written even when
        *cmd* fails -- ``&&`` silently drops it on non-zero exit (#439)."""
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            exec_mod, "read_file", MagicMock(return_value="ok\nVIP_DONE_deadbeef:0")
        )
        page = MagicMock()

        exec_mod.terminal_run(page, "false", timeout=1_000)

        typed_cmd = page.locator.return_value.type.call_args[0][0]
        assert "&&" not in typed_cmd
        assert 'echo "VIP_DONE_deadbeef:$?"' in typed_cmd

    def test_returns_output_on_success(self, monkeypatch):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(
            exec_mod, "read_file", MagicMock(return_value="hello\nVIP_DONE_deadbeef:0")
        )
        page = MagicMock()

        result = exec_mod.terminal_run(page, "echo hello", timeout=1_000)

        assert result == "hello"

    def test_raises_exec_error_immediately_on_nonzero_exit(self, monkeypatch):
        """Fast failure must surface as an immediate ExecError with the real
        output, not a 120s timeout with the output discarded."""
        self._patch_common(monkeypatch)
        error_output = "fatal: destination path 'repo' already exists"
        mock_read_file = MagicMock(return_value=f"{error_output}\nVIP_DONE_deadbeef:128")
        monkeypatch.setattr(exec_mod, "read_file", mock_read_file)
        page = MagicMock()

        with pytest.raises(ExecError, match="128") as excinfo:
            exec_mod.terminal_run(page, "git clone ...", timeout=1_000)

        assert error_output in str(excinfo.value)
        # Must not have looped until timeout -- a single poll is enough.
        mock_read_file.assert_called_once()

    def test_still_times_out_when_marker_never_appears(self, monkeypatch):
        """A genuinely hung command (no marker at all) still times out."""
        self._patch_common(monkeypatch)
        monkeypatch.setattr(exec_mod, "read_file", MagicMock(return_value="still running..."))
        monkeypatch.setattr(exec_mod.time, "sleep", lambda s: None)
        page = MagicMock()

        with pytest.raises(ExecError, match="timed out"):
            exec_mod.terminal_run(page, "sleep 999", timeout=10)

    def _patch_vscode(self, monkeypatch, content):
        """VS Code polls via editor-open/read/close instead of ``read_file``."""
        self._patch_common(monkeypatch, ide="vscode")
        monkeypatch.setattr(
            exec_mod, "_open_file_in_vscode_editor", lambda p, path, timeout=5_000: None
        )
        monkeypatch.setattr(exec_mod, "_close_active_editor", lambda p: None)
        mock_read = MagicMock(return_value=content)
        monkeypatch.setattr(exec_mod, "_read_vscode_editor_text", mock_read)
        return mock_read

    def test_vscode_returns_output_on_success(self, monkeypatch):
        """The VS Code editor-open polling path has its own copy of the
        marker-parsing logic and must be covered independently of the
        RStudio/Positron ``read_file`` path exercised above."""
        self._patch_vscode(monkeypatch, "hello\nVIP_DONE_deadbeef:0")
        page = MagicMock()

        result = exec_mod.terminal_run(page, "echo hello", timeout=1_000)

        assert result == "hello"

    def test_vscode_raises_exec_error_immediately_on_nonzero_exit(self, monkeypatch):
        """Regression guard: the VS Code branch must also raise ExecError
        immediately on failure rather than looping until timeout (#439)."""
        error_output = "fatal: destination path 'repo' already exists"
        mock_read = self._patch_vscode(monkeypatch, f"{error_output}\nVIP_DONE_deadbeef:128")
        page = MagicMock()

        with pytest.raises(ExecError, match="128") as excinfo:
            exec_mod.terminal_run(page, "git clone ...", timeout=1_000)

        assert error_output in str(excinfo.value)
        mock_read.assert_called_once()
