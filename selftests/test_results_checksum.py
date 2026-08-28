import hashlib
import subprocess
import sys

import pytest


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
