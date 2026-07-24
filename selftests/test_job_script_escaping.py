"""Guard against a raw newline reaching the console as a premature Enter keypress.

``_run_console_command`` types R commands via Playwright's ``type()``, which
aliases embedded "\n"/"\r" characters to the Enter key — a raw newline in the
command submits it early, splitting it into two invalid R statements (see the
regression where ``write_test_script``'s ``writeLines()`` call never created
the test job script).
"""

from __future__ import annotations

import pytest

from vip_tests.workbench.test_jobs import _JOB_SCRIPT_CONTENT, _escape_for_r_string_literal


def test_job_script_content_has_no_raw_newline_after_escaping():
    escaped = _escape_for_r_string_literal(_JOB_SCRIPT_CONTENT)
    assert "\n" not in escaped
    assert "\r" not in escaped


@pytest.mark.parametrize(
    "content",
    ["line one\nline two", 'has a "quote"\nand a newline', "carriage\rreturn"],
)
def test_escape_removes_raw_newlines_and_carriage_returns(content):
    escaped = _escape_for_r_string_literal(content)
    assert "\n" not in escaped
    assert "\r" not in escaped
