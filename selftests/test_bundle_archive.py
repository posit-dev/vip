"""Tests for the ``vip bundle`` archive builder and secret scan."""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from vip.bundle.archive import (
    collect_members,
    find_secret_hits,
    short_secret_labels,
    write_zip,
)
from vip.bundle.stamp import STAMP_NAME, record_rendered, results_digest
from vip.errors import BundleError

_SIDECARS = ("failures.json", "junit.xml", "results.sarif")
_RENDERED = ("index.html", "details.html", "vip-report.pdf")
_RESULTS = json.dumps({"deployment_name": "Acme", "results": []})


def _write(path: Path, text: str, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))


def _seed(
    report: Path,
    sidecars=_SIDECARS,
    rendered=_RENDERED,
    results: str = _RESULTS,
    results_mtime: float = 1_000_000.0,
) -> None:
    """Write a report directory as ``vip verify`` and ``vip report`` leave it.

    Each sidecar is one second newer than results.json. The render stamp
    names each rendered file and the digest of results.json.
    """
    _write(report / "results.json", results, results_mtime)
    for name in sidecars:
        _write(report / name, f"content of {name}", results_mtime + 1)
    for name in rendered:
        _write(report / "_output" / name, f"content of {name}", results_mtime + 2)
    if rendered:
        record_rendered(report / "_output", results_digest(results.encode()), rendered)


def _all_members() -> set[str]:
    return (
        {"report/results.json"}
        | {f"report/{n}" for n in _SIDECARS}
        | {f"report/_output/{n}" for n in _RENDERED}
    )


def test_collects_only_allowlisted_files(tmp_path):
    report = tmp_path / "report"
    _seed(report)
    for name in ("notes.txt", "index.qmd", "_output/search.json", "_output/site_libs/b.css"):
        _write(report / name, "x", 2_000_000.0)
    got = collect_members(report / "results.json", report)
    assert set(got.members) == _all_members()
    assert got.missing == []
    assert got.left_out == []
    assert got.warnings == []
    assert got.sources["report/failures.json"] == report / "failures.json"


def test_optional_files_absent_is_not_an_error(tmp_path):
    report = tmp_path / "report"
    _seed(report, sidecars=(), rendered=())
    got = collect_members(report / "results.json", report)
    assert set(got.members) == {"report/results.json"}
    assert "report/failures.json" in got.missing
    assert "report/_output/vip-report.pdf" in got.missing
    assert any("Run 'vip report'" in w for w in got.warnings)


def test_missing_results_raises(tmp_path):
    with pytest.raises(BundleError, match=r"results\.json"):
        collect_members(tmp_path / "report/results.json", tmp_path / "report")


@pytest.mark.parametrize("name", ["vip.toml", ".vip-auth-cache.json", ".vip-install.json"])
def test_results_cannot_name_a_credential_file(tmp_path, name):
    path = tmp_path / name
    path.write_text('{"results": []}', encoding="utf-8")
    with pytest.raises(BundleError, match="is not a results file"):
        collect_members(path, tmp_path / "report")


@pytest.mark.parametrize("text", ["api_key = 'x'", "[]", '{"no_results": 1}'])
def test_results_must_be_a_vip_results_file(tmp_path, text):
    path = tmp_path / "results.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(BundleError, match="is not a VIP results file"):
        collect_members(path, tmp_path / "report")


def test_render_from_other_results_is_left_out(tmp_path):
    # The user ran vip verify again but not vip report.
    report = tmp_path / "report"
    _seed(report)
    _write(report / "results.json", json.dumps({"results": [{"new": 1}]}), 3_000_000.0)
    for name in _SIDECARS:
        os.utime(report / name, (3_000_001.0, 3_000_001.0))
    got = collect_members(report / "results.json", report)
    assert not any(name.startswith("report/_output/") for name in got.members)
    assert {item["name"] for item in got.left_out} == {f"report/_output/{n}" for n in _RENDERED}
    assert all(item["reason"].startswith("was not made from") for item in got.left_out)
    assert sum("Run 'vip report' again" in w for w in got.warnings) == 3


def test_copied_results_with_an_old_time_does_not_let_in_an_old_render(tmp_path):
    # vip report --results copies with shutil.copy2, which keeps the old file
    # time. If the PDF step then fails, the PDF of the earlier run stays and
    # is newer than results.json. Only the stamp shows that it is foreign.
    report = tmp_path / "report"
    _seed(report, results_mtime=2_000_000.0)
    ci = tmp_path / "ci-results.json"
    _write(ci, json.dumps({"results": [{"ci": 1}]}), 1_500_000.0)
    shutil.copy2(ci, report / "results.json")
    record_rendered(report / "_output", results_digest(ci.read_bytes()), ("index.html",))
    got = collect_members(report / "results.json", report)
    assert "report/_output/index.html" in got.members
    assert "report/_output/vip-report.pdf" not in got.members
    assert "report/_output/details.html" not in got.members


def test_results_outside_report_dir_keeps_render_with_the_same_content(tmp_path):
    report = tmp_path / "report"
    _seed(report)
    other = tmp_path / "out" / "run1.json"
    _write(other, _RESULTS, 1_000_000.0)
    got = collect_members(other, report)
    assert {f"report/_output/{n}" for n in _RENDERED} <= set(got.members)


def test_results_outside_report_dir_leaves_out_other_render(tmp_path):
    report = tmp_path / "report"
    _seed(report)
    other = tmp_path / "other" / "results.json"
    _write(other, json.dumps({"results": [{"other": 1}]}), 2_000_000.0)
    got = collect_members(other, report)
    assert set(got.members) == {"report/results.json"}
    assert any(f"was not made from {other}" in w for w in got.warnings)


def test_render_without_a_stamp_is_left_out(tmp_path):
    # A render from a vip version that writes no stamp, or a render that failed.
    report = tmp_path / "report"
    _seed(report)
    (report / "_output" / STAMP_NAME).unlink()
    got = collect_members(report / "results.json", report)
    assert not any(name.startswith("report/_output/") for name in got.members)


def test_stale_sidecar_is_left_out(tmp_path):
    # failures.json from an earlier run that failed. The new run passed, so
    # vip verify did not write a new failures.json.
    report = tmp_path / "report"
    _seed(report)
    os.utime(report / "failures.json", (999_000.0, 999_000.0))
    got = collect_members(report / "results.json", report)
    assert "report/failures.json" not in got.members
    assert {"name": "report/failures.json", "reason": "is older than results.json"} in (
        got.left_out
    )
    assert any(str(report / "failures.json") in w for w in got.warnings)


def _seed_run_pair(report: Path, results_run: str, failures_run: str) -> None:
    """Write results.json and failures.json with a ``generated_at`` value each."""
    results = json.dumps({"generated_at": results_run, "results": []})
    _seed(report, sidecars=(), rendered=(), results=results)
    failures = json.dumps({"generated_at": failures_run, "failures": []})
    _write(report / "failures.json", failures, 1_000_001.0)


def test_failures_json_of_the_same_run_stays_when_results_is_newer(tmp_path):
    # An edit of results.json gives it a newer file time than failures.json.
    report = tmp_path / "report"
    _seed_run_pair(report, "2026-11-12T14:00:00+00:00", "2026-11-12T14:00:00+00:00")
    os.utime(report / "results.json", (1_000_500.0, 1_000_500.0))
    got = collect_members(report / "results.json", report)
    assert "report/failures.json" in got.members
    assert got.left_out == []


def test_failures_json_of_another_run_is_left_out_when_it_is_newer(tmp_path):
    report = tmp_path / "report"
    _seed_run_pair(report, "2026-11-12T14:00:00+00:00", "2026-11-12T15:00:00+00:00")
    got = collect_members(report / "results.json", report)
    assert "report/failures.json" not in got.members
    assert got.left_out == [
        {"name": "report/failures.json", "reason": "is from a different run than results.json"}
    ]


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_symlinks_are_left_out(tmp_path):
    report = tmp_path / "report"
    _seed(report, sidecars=(), rendered=())
    secret = tmp_path / "vip.toml"
    secret.write_text("api_key = 'x'", encoding="utf-8")
    (report / "failures.json").symlink_to(secret)
    (report / "_output").mkdir()
    (report / "_output" / "index.html").symlink_to(secret)
    got = collect_members(report / "results.json", report)
    assert set(got.members) == {"report/results.json"}
    assert sum("is a link" in w for w in got.warnings) == 2


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_symlinked_output_dir_is_left_out(tmp_path):
    report = tmp_path / "report"
    _seed(report, rendered=())
    elsewhere = tmp_path / "elsewhere"
    _seed(elsewhere)
    (report / "_output").symlink_to(elsewhere / "_output")
    got = collect_members(report / "results.json", report)
    assert not any(name.startswith("report/_output/") for name in got.members)


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_symlinked_results_raises(tmp_path):
    report = tmp_path / "report"
    report.mkdir()
    real = tmp_path / "real.json"
    real.write_text(_RESULTS, encoding="utf-8")
    (report / "results.json").symlink_to(real)
    with pytest.raises(BundleError, match="is a link"):
        collect_members(report / "results.json", report)


# Shorter than 16 characters, so only the full value is scanned. Each case
# below then passes only through the encoded form that it names.
SHORT = 'pa"ss&wörd-01'
SPACED = "pass word-0123"
BACKSLASH = "ab\\cd-Secret9"
WRAPPED = "Wrap-Me-1234"
# At least 16 characters, so the scan also looks for the first and the last 8.
LONG = "K3y-Start-0123456789-a1b2c3d4e5"
QUOTED = 'p"ss\\w0rd-ABCDEFGHIJ0123'
PADDED = "QU1DREVGR0hJSktMTU5PUA=="


@pytest.mark.parametrize(
    ("secret", "stored"),
    [
        (SHORT, SHORT.encode()),
        (SHORT, b'pa\\"ss&w\\u00f6rd-01'),  # json.dumps with ensure_ascii
        (SHORT, 'pa\\"ss&wörd-01'.encode()),  # json.dumps without ensure_ascii
        (SHORT, "pa&quot;ss&amp;wörd-01".encode()),  # html.escape
        (SHORT, 'pa"ss&amp;wörd-01'.encode()),  # html.escape with quote=False (XML text)
        (SHORT, b"pa%22ss%26w%C3%B6rd-01"),  # percent-encoded with quote
        (SPACED, b"pass+word-0123"),  # percent-encoded with quote_plus
        (BACKSLASH, b"'ab\\\\cd-Secret9'"),  # repr in error text
        (BACKSLASH, json.dumps(repr(BACKSLASH)).encode()),  # repr, then json.dumps
        (WRAPPED, b"Wrap\n-Me-1234"),  # wrapped across lines
        (WRAPPED, b"Wrap\\n-Me-1234"),  # wrapped, then json.dumps
        (LONG, LONG[:10].encode()),  # cut at a length limit
        (LONG, b"..." + LONG[-12:].encode()),  # cut in the middle by pytest saferepr
        (QUOTED, json.dumps(QUOTED[:10])[1:-1].encode()),  # cut, then json.dumps
        (PADDED, PADDED[:12].encode()),  # a value with "=" still gets a partial form
    ],
)
def test_find_secret_hits_sees_encoded_forms(secret, stored):
    members = {"report/a": b"x " + stored + b" y", "report/b": b"clean"}
    assert find_secret_hits(members, [("auth.password", secret)]) == [("report/a", "auth.password")]


def test_find_secret_hits_finds_nothing_in_clean_members():
    members = {"report/a": b"nothing here", "report/b": b"clean"}
    assert find_secret_hits(members, [("connect.api_key", "ABC123")]) == []


@pytest.mark.parametrize(
    ("conn", "text"),
    [
        ("Host=db01;Port=5432;Password=Xy9-secret-value", b"could not reach Host=db01:5432"),
        ("pg15://dbuser:DB-PASSWORD-01@db:5432/app", b"engine pg15://..."),
    ],
)
def test_partial_rule_skips_connection_strings(conn, text):
    # The start of a whole connection string or URL is a key or a scheme, which
    # is in normal error text. Its credential parts are separate secrets.
    assert find_secret_hits({"report/a": text}, [("db", conn)]) == []


def test_partial_rule_skips_the_start_of_a_jwt():
    # Every JWT starts with eyJhbGci, which has no digit, so only the end of a
    # JWT is a partial form.
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ2aXAifQ.c2lnbmF0dXJlLX9hbH1l"
    other = b"token eyJhbGciOiJSUzI1NiJ9.other"
    assert find_secret_hits({"report/a": other}, [("package_manager.token", jwt)]) == []
    tail = jwt[-10:].encode()
    assert find_secret_hits({"report/a": tail}, [("package_manager.token", jwt)]) == [
        ("report/a", "package_manager.token")
    ]


def test_partial_rule_skips_a_part_with_no_digit_or_no_letter():
    # A password that ends in a word must not match every "password_set" key.
    secrets = [("auth.password", "Company-Secret-password"), ("x", "abcdefgh-20261105")]
    members = {"config-summary.json": b'"password_set": true, "date": "20261105"'}
    assert find_secret_hits(members, secrets) == []


def test_short_secrets_are_not_scanned_but_are_reported():
    secrets = [("auth.password", "abc"), ("connect.api_key", "ABC123")]
    assert find_secret_hits({"report/a": b"abc"}, secrets) == []
    assert short_secret_labels(secrets) == ["auth.password"]


def test_write_zip_writes_every_member(tmp_path):
    out = tmp_path / "b.zip"
    write_zip(out, {"y": b"2", "x": b"1"})
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["x", "y"]
        assert zf.read("y") == b"2"


def test_write_zip_leaves_nothing_on_error(tmp_path, monkeypatch):
    real_writestr = zipfile.ZipFile.writestr
    calls: list[str] = []

    def failing_writestr(self, name, data, *args, **kwargs):
        calls.append(name)
        if len(calls) == 2:
            raise OSError("disk full")
        return real_writestr(self, name, data, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", failing_writestr)
    with pytest.raises(OSError, match="disk full"):
        write_zip(tmp_path / "b.zip", {"x": b"1", "y": b"2"})
    assert list(tmp_path.iterdir()) == []
