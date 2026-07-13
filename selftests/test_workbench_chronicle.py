"""Unit tests for the in-session Chronicle raw-chunk probe expression.

The probe logic lives in ``chronicle_probe.R``; ``chronicle_probe.py`` flattens
it to a single line and appends a parameterized call. These tests validate that
flattening and the resulting expression without a browser — the actual
in-session evaluation is exercised against a live Chronicle-enabled Workbench.
"""

from __future__ import annotations

from pathlib import Path

from vip_tests.workbench.chronicle_probe import (
    TOKEN_NO_DATA,
    TOKEN_OK,
    raw_chunk_probe_expr,
)

BASE = "/var/lib/rstudio-server/shared-storage/chronicle"
_R_FILE = Path("src/vip_tests/workbench/chronicle_probe.R")


class TestRawChunkProbeExpr:
    def test_is_single_line(self):
        # rstudio_eval types the expression into the console as one line; a
        # newline would submit a truncated statement.
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "\n" not in expr

    def test_flattening_drops_comments(self):
        # Full-line comments in the .R file must not survive flattening — a
        # stray "#" would comment out the rest of the one-liner.
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "#" not in expr

    def test_defines_and_calls_the_probe_function(self):
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "vip_chronicle_probe <- function(base_path, metric)" in expr
        assert f'cat(vip_chronicle_probe("{BASE}", "pwb_users"))' in expr

    def test_matches_metric_dir_with_trailing_slash(self):
        # The trailing slash prevents pwb_users from matching pwb_users_totals.
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert 'paste0("/v2/", metric, "/")' in expr

    def test_matches_csv_and_parquet_chunks(self):
        # Chunk filenames are unstable (bare UUIDs or a chronicle-data-* stem),
        # so the probe matches by extension under the metric dir, not by name.
        expr = raw_chunk_probe_expr(BASE, "pwb_active_user_sessions")
        assert 'pattern = "[.](csv|parquet)$"' in expr
        assert "recursive = TRUE" in expr

    def test_filters_out_empty_files(self):
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "file.info(files)$size > 0" in expr

    def test_reads_newest_chunk(self):
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "decreasing = TRUE" in expr
        assert "readLines" in expr

    def test_requires_chunk_to_be_readable(self):
        # A chunk the session user cannot open (e.g. permission denied) must
        # report no data rather than a false positive, so the probe checks
        # read access before attempting to read the file.
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "file.access(newest, mode = 4) != 0" in expr

    def test_non_csv_chunk_counts_as_data(self):
        # readLines failing (e.g. a Parquet chunk) yields NA; the expression
        # must treat a non-empty non-CSV chunk as data present, not absent.
        expr = raw_chunk_probe_expr(BASE, "pwb_users")
        assert "is.na(n) || n > 1" in expr

    def test_custom_base_path(self):
        expr = raw_chunk_probe_expr("/mnt/chronicle", "pwb_users")
        assert 'cat(vip_chronicle_probe("/mnt/chronicle", "pwb_users"))' in expr


class TestTokensInSyncWithRFile:
    def test_tokens_match_r_source(self):
        # The .R file hard-codes the sentinel strings; the Python constants must
        # match them so test_chronicle can interpret the probe's output.
        r_source = _R_FILE.read_text()
        assert f'"{TOKEN_OK}"' in r_source
        assert f'"{TOKEN_NO_DATA}"' in r_source
