"""Builder for the in-session Chronicle raw-chunk probe expression.

The probe logic lives in ``chronicle_probe.R`` as a normal, readable R function.
``rstudio_eval`` types the expression into the console as a single line, so this
module flattens that file into one line (dropping comment/blank lines and joining
statements with ``"; "``) and appends the parameterized call. Kept separate from
``test_chronicle.py`` (which carries the pytest-bdd ``@scenario`` and Playwright
imports) so the builder can be unit tested without a browser — see
``selftests/test_workbench_chronicle.py``.
"""

from __future__ import annotations

from pathlib import Path

# Sentinel tokens the probe returns (exactly one). Must match the string
# literals in chronicle_probe.R; a selftest guards that they stay in sync.
TOKEN_OK = "VIP_DATA_OK"
TOKEN_NO_DATA = "VIP_NO_DATA"

_PROBE_R_FILE = Path(__file__).with_name("chronicle_probe.R")


def _flatten_r(source: str) -> str:
    """Collapse an R source file to a single console-safe line.

    Drops blank lines and full-line ``#`` comments, then joins the remaining
    statements with ``"; "``. This is safe only because ``chronicle_probe.R`` is
    written with one complete statement per line and no inline comments (see the
    header comment there).
    """
    lines = [line.strip() for line in source.splitlines()]
    statements = [line for line in lines if line and not line.startswith("#")]
    return "; ".join(statements)


# Flatten once at import; the R file is static (the call is parameterized below).
_PROBE_FN = _flatten_r(_PROBE_R_FILE.read_text())


def raw_chunk_probe_expr(base_path: str, metric: str) -> str:
    """Return the one-line R expression that probes one raw Chronicle metric.

    Defines ``vip_chronicle_probe`` (from chronicle_probe.R) and calls it for
    *base_path* / *metric*, printing exactly one sentinel token (``TOKEN_OK`` or
    ``TOKEN_NO_DATA``). ``base_path`` and ``metric`` are embedded as R string
    literals; callers must reject values containing a double quote (see
    ``test_chronicle._safe_r_literal``).
    """
    return f'{_PROBE_FN}; cat(vip_chronicle_probe("{base_path}", "{metric}"))'
