"""Selftests for the workbench.exec pure-logic helpers.

These tests cover the deterministic, Playwright-free functions extracted from
``src/vip_tests/workbench/exec.py``:

- ``_wrap_r_expr`` / ``_wrap_python_expr`` — marker-bracketed expression fencing
- ``_extract_between_markers`` — output extraction between UUID sentinels
- ``_strip_r_index`` — R vector-index prefix stripping
- ``_make_sentinels`` — UUID sentinel format validation
- Error-path behavior (missing start/end markers)

No live Workbench deployment or Playwright browser is required.
"""

from __future__ import annotations

import re

import pytest

from vip_tests.workbench.exec import (
    ExecError,
    _extract_between_markers,
    _make_sentinels,
    _strip_r_index,
    _wrap_python_expr,
    _wrap_r_expr,
)


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
    def test_contains_start_marker(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_r_expr("1 + 1", start, end)
        assert start in result

    def test_contains_end_marker(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_r_expr("1 + 1", start, end)
        assert end in result

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
        # Start marker should appear before the expression in the output string
        assert result.index(start) < result.index("1 + 1")
        assert result.index("1 + 1") < result.index(end)

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
    def test_contains_start_marker(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("1 + 1", start, end)
        assert start in result

    def test_contains_end_marker(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("1 + 1", start, end)
        assert end in result

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
        assert start in first_line

    def test_end_print_is_last_line(self):
        start, end = "<<VIP-START-abc>>", "<<VIP-END-abc>>"
        result = _wrap_python_expr("x = 1", start, end)
        last_line = result.splitlines()[-1]
        assert end in last_line


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
        """Simulates what the console would echo back for an R eval."""
        start, end = _make_sentinels()
        wrapped = _wrap_r_expr("1 + 1", start, end)
        # Simulate console output: echo of command + output between markers
        simulated_output = f"some prior output\n{start}\n[1] 2\n{end}\n> "
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
