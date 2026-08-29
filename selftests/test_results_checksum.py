import hashlib
import shutil
import subprocess
import sys

import pytest

from vip.cli import _rehome_sidecar
from vip.traceability import ResultsIntegrityError, verify_results_checksum


def test_sidecar_matches_the_bytes_on_disk(pytester):
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")

    sidecar = report.parent / "results.json.sha256"
    assert sidecar.exists()

    expected = hashlib.sha256(report.read_bytes()).hexdigest()
    line = sidecar.read_text().strip()
    digest, name = line.split()
    assert digest == expected
    assert name == "results.json"


def test_sidecar_is_written_even_for_json_only_format(pytester):
    """The checksum is a property of the file, not an output format."""
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess(
        "--vip-report", str(report), "--vip-format", "json", "-p", "no:cacheprovider"
    )
    assert (report.parent / "results.json.sha256").exists()


def test_sidecar_verifies_with_shasum(pytester):
    if sys.platform.startswith("win"):
        pytest.skip("shasum not available on Windows")
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")
    try:
        proc = subprocess.run(
            ["shasum", "-a", "256", "-c", "results.json.sha256"],
            cwd=report.parent,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        pytest.skip("shasum binary not found on PATH")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_sidecar_failure_does_not_suppress_requested_outputs(pytester):
    """Verify that a sidecar write failure does not gate requested outputs like junit.xml."""
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    report_dir = report.parent

    # Create a directory at the sidecar path to cause OSError on sidecar write.
    sidecar_dir = report_dir / "results.json.sha256"
    sidecar_dir.mkdir(parents=True)

    # Run with both json and junit formats: both should succeed despite sidecar failure.
    pytester.runpytest_subprocess(
        "--vip-report",
        str(report),
        "--vip-format",
        "json,junit",
        "-p",
        "no:cacheprovider",
    )

    # Both requested outputs must exist; sidecar failure is not fatal.
    assert report.exists(), "results.json should exist despite sidecar failure"
    junit_xml = report_dir / "junit.xml"
    assert junit_xml.exists(), "junit.xml should exist despite sidecar failure"


class TestSidecarParsing:
    """Both failure directions: a false tamper alarm and a false attestation."""

    def _results(self, tmp_path):
        p = tmp_path / "results.json"
        p.write_text('{"schema_version": "1.0", "results": []}', encoding="utf-8")
        return p, hashlib.sha256(p.read_bytes()).hexdigest()

    def test_uppercase_digest_verifies(self, tmp_path):
        """Get-FileHash and 7-Zip emit uppercase; hex case is not a mismatch."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest.upper()}  results.json\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_binary_mode_marker_is_tolerated(self, tmp_path):
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest} *results.json\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_utf8_bom_is_tolerated(self, tmp_path):
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_bytes(
            b"\xef\xbb\xbf" + f"{digest}  results.json\n".encode()
        )
        assert verify_results_checksum(p) == (digest, True)

    def test_multi_file_sidecar_matches_the_right_line(self, tmp_path):
        """A flat .split() would compare the first line's digest to this file."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(
            f"{'0' * 64}  failures.json\n{digest}  results.json\n"
        )
        assert verify_results_checksum(p) == (digest, True)

    def test_sidecar_naming_a_different_file_is_refused(self, tmp_path):
        """The false-attestation case: matching digest, wrong file."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest}  totally_other.json\n")
        with pytest.raises(ResultsIntegrityError, match="does not record an entry"):
            verify_results_checksum(p)

    def test_bare_digest_without_a_filename_still_verifies(self, tmp_path):
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest}\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_genuine_mismatch_is_still_refused(self, tmp_path):
        p, _ = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{'a' * 64}  results.json\n")
        with pytest.raises(ResultsIntegrityError, match="checksum mismatch"):
            verify_results_checksum(p)

    def test_path_qualified_sidecar_verifies(self, tmp_path):
        """`shasum -a 256 report/results.json` from a parent directory."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest}  report/results.json\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_windows_path_qualified_sidecar_verifies(self, tmp_path):
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(f"{digest}  report\\results.json\n")
        assert verify_results_checksum(p) == (digest, True)

    def test_exact_match_still_wins_over_a_basename_collision(self, tmp_path):
        """A sidecar naming this file exactly never reaches the fallback."""
        p, digest = self._results(tmp_path)
        p.with_name("results.json.sha256").write_text(
            f"{'0' * 64}  archive/results.json\n{digest}  results.json\n"
        )
        assert verify_results_checksum(p) == (digest, True)


class TestStaleSidecarInvalidation:
    def test_writing_results_removes_a_stale_sidecar_first(self, tmp_path, pytester):
        """A sidecar write that fails must not leave the previous run's digest."""
        from vip.plugin import pytest_sessionfinish  # noqa: F401  (import guard only)

        results = tmp_path / "results.json"
        results.write_text("old", encoding="utf-8")
        sidecar = tmp_path / "results.json.sha256"
        sidecar.write_text(f"{'0' * 64}  results.json\n", encoding="utf-8")

        pytester.makepyfile(test_x="def test_x():\n    assert True\n")
        pytester.runpytest_subprocess(
            f"--vip-report={results}", "-p", "no:cacheprovider", "--vip-no-attribution"
        )

        digest, present = verify_results_checksum(results)
        assert present is True
        assert digest == hashlib.sha256(results.read_bytes()).hexdigest()


class TestReportSidecarRehoming:
    """`vip report --results` copies a results file; the sidecar must follow it."""

    def _sidecar_for(self, path):
        return path.with_name(f"{path.name}.sha256")

    def test_source_sidecar_is_rehomed_under_the_destination_name(self, tmp_path):
        src = tmp_path / "run-42.json"
        src.write_text('{"results": []}', encoding="utf-8")
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        self._sidecar_for(src).write_text(f"{digest}  run-42.json\n", encoding="utf-8")

        dest = tmp_path / "out" / "results.json"
        dest.parent.mkdir()
        shutil.copy2(src, dest)
        _rehome_sidecar(self._sidecar_for(src), self._sidecar_for(dest), src.name, dest.name)

        assert verify_results_checksum(dest) == (digest, True)

    def test_digest_is_carried_not_recomputed(self, tmp_path):
        """Recomputing would launder a tampered file into a verified one."""
        src = tmp_path / "results.json"
        src.write_text("tampered", encoding="utf-8")
        self._sidecar_for(src).write_text(f"{'0' * 64}  results.json\n", encoding="utf-8")

        dest = tmp_path / "out" / "results.json"
        dest.parent.mkdir()
        shutil.copy2(src, dest)
        _rehome_sidecar(self._sidecar_for(src), self._sidecar_for(dest), src.name, dest.name)

        with pytest.raises(ResultsIntegrityError, match="checksum mismatch"):
            verify_results_checksum(dest)

    def test_missing_source_sidecar_removes_the_stale_destination_one(self, tmp_path):
        dest = tmp_path / "results.json"
        dest.write_text('{"results": []}', encoding="utf-8")
        self._sidecar_for(dest).write_text(f"{'0' * 64}  results.json\n", encoding="utf-8")

        _rehome_sidecar(tmp_path / "absent.json.sha256", self._sidecar_for(dest), "a", dest.name)

        assert not self._sidecar_for(dest).exists()
        _, present = verify_results_checksum(dest)
        assert present is False
