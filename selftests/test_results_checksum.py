import hashlib
import subprocess
import sys


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
        return
    pytester.makepyfile(test_x="def test_ok(): assert True")
    report = pytester.path / "results.json"
    pytester.runpytest_subprocess("--vip-report", str(report), "-p", "no:cacheprovider")
    proc = subprocess.run(
        ["shasum", "-a", "256", "-c", "results.json.sha256"],
        cwd=report.parent,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
