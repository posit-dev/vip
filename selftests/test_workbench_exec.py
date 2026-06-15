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
    _split_marker,
    _strip_r_index,
    _wrap_python_expr,
    _wrap_r_expr,
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

    def test_vscode_detected_without_positron_console(self):
        page = _make_page_mock({VSCodeSession.WORKBENCH})
        assert _detect_ide(page) == "vscode"

    def test_unknown_when_nothing_present(self):
        page = _make_page_mock(set())
        assert _detect_ide(page) == "unknown"


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
        mock_rstudio_eval = MagicMock(return_value="[1] hello world")
        mock_positron_eval_r = MagicMock()
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = read_file(page, "/tmp/foo.txt", lang="r")

        assert result == "hello world"  # _strip_r_index applied
        mock_rstudio_eval.assert_called_once()
        mock_positron_eval_r.assert_not_called()
        mock_positron_eval_python.assert_not_called()
        mock_editor_read.assert_not_called()

    def test_positron_r_calls_positron_eval_r(self, monkeypatch):
        page = MagicMock()
        monkeypatch.setattr(exec_mod, "_detect_ide", lambda p: "positron")
        mock_rstudio_eval = MagicMock()
        mock_positron_eval_r = MagicMock(return_value="[1] file contents")
        mock_positron_eval_python = MagicMock()
        mock_editor_read = MagicMock()
        monkeypatch.setattr(exec_mod, "rstudio_eval", mock_rstudio_eval)
        monkeypatch.setattr(exec_mod, "positron_eval_r", mock_positron_eval_r)
        monkeypatch.setattr(exec_mod, "positron_eval_python", mock_positron_eval_python)
        monkeypatch.setattr(exec_mod, "read_file_via_vscode_editor", mock_editor_read)

        result = read_file(page, "/tmp/foo.txt", lang="r")

        assert result == "file contents"  # _strip_r_index applied
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
