"""Tests for ``vip --version`` and ``vip --product-versions``.

``vip --product-versions`` derives its output from the ``@pytest.mark.min_version``
markers in the shipped test suite, so it cannot drift from the tests.
"""

from __future__ import annotations

import sys

import pytest


def _write(path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


class TestScanTargetedProductVersions:
    """scan_targeted_product_versions() derives targets from the suite markers."""

    def test_returns_highest_version_per_product(self, tmp_path, monkeypatch):
        import vip.product_targets as pt

        _write(
            tmp_path / "test_a.py",
            "import pytest\n"
            '@pytest.mark.min_version(product="connect", version="2026.01.0")\n'
            "def test_a():\n    pass\n",
        )
        _write(
            tmp_path / "test_b.py",
            "import pytest\n"
            '@pytest.mark.min_version(product="connect", version="2026.06.0")\n'
            "def test_b():\n    pass\n",
        )
        monkeypatch.setattr(pt, "_tests_root", lambda: tmp_path)

        assert pt.scan_targeted_product_versions() == {"Connect": "2026.06.0"}

    def test_maps_product_ids_to_display_names(self, tmp_path, monkeypatch):
        import vip.product_targets as pt

        _write(
            tmp_path / "test_x.py",
            "import pytest\n"
            '@pytest.mark.min_version(product="package_manager", version="2026.02.0")\n'
            "def test_x():\n    pass\n",
        )
        monkeypatch.setattr(pt, "_tests_root", lambda: tmp_path)

        assert pt.scan_targeted_product_versions() == {"Package Manager": "2026.02.0"}

    def test_handles_positional_marker_args(self, tmp_path, monkeypatch):
        import vip.product_targets as pt

        _write(
            tmp_path / "test_pos.py",
            "import pytest\n"
            '@pytest.mark.min_version("workbench", "2026.03.0")\n'
            "def test_pos():\n    pass\n",
        )
        monkeypatch.setattr(pt, "_tests_root", lambda: tmp_path)

        assert pt.scan_targeted_product_versions() == {"Workbench": "2026.03.0"}

    def test_skips_malformed_versions(self, tmp_path, monkeypatch):
        import vip.product_targets as pt

        _write(
            tmp_path / "test_bad.py",
            "import pytest\n"
            '@pytest.mark.min_version(product="connect", version="not-a-version")\n'
            "def test_bad():\n    pass\n",
        )
        monkeypatch.setattr(pt, "_tests_root", lambda: tmp_path)

        assert pt.scan_targeted_product_versions() == {}

    def test_ignores_unrelated_decorators(self, tmp_path, monkeypatch):
        import vip.product_targets as pt

        _write(
            tmp_path / "test_other.py",
            "import pytest\n@pytest.mark.connect\ndef test_other():\n    pass\n",
        )
        monkeypatch.setattr(pt, "_tests_root", lambda: tmp_path)

        assert pt.scan_targeted_product_versions() == {}

    def test_missing_tests_root_returns_empty(self, monkeypatch):
        import vip.product_targets as pt

        monkeypatch.setattr(pt, "_tests_root", lambda: None)
        assert pt.scan_targeted_product_versions() == {}

    def test_real_suite_reflects_connect_marker(self):
        from vip.product_targets import scan_targeted_product_versions

        # The suite ships @pytest.mark.min_version(product="connect", ...).
        targets = scan_targeted_product_versions()
        assert "Connect" in targets


class TestVersionFlag:
    """``vip --version`` prints the vip version and exits 0."""

    def test_prints_version_and_exits(self, capsys, monkeypatch):
        from vip import __version__
        from vip.cli import main

        monkeypatch.setattr(sys, "argv", ["vip", "--version"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert out.strip() == f"vip {__version__}"

    def test_does_not_list_product_versions(self, capsys, monkeypatch):
        from vip.cli import main

        monkeypatch.setattr(sys, "argv", ["vip", "--version"])
        with pytest.raises(SystemExit):
            main()
        out = capsys.readouterr().out
        assert "connect" not in out.lower()


class TestProductVersionsFlag:
    """``vip --product-versions`` prints the derived targets and exits 0."""

    def test_prints_derived_versions_and_exits(self, capsys, monkeypatch):
        from vip.cli import main
        from vip.product_targets import scan_targeted_product_versions

        monkeypatch.setattr(sys, "argv", ["vip", "--product-versions"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        targets = scan_targeted_product_versions()
        assert targets, "expected the real suite to yield at least one target"
        for product, version in targets.items():
            assert product in out
            assert version in out

    def test_placeholder_when_no_markers(self, capsys, monkeypatch):
        from vip import cli

        monkeypatch.setattr(cli, "_scan_targeted_product_versions", lambda: {})
        monkeypatch.setattr(sys, "argv", ["vip", "--product-versions"])
        with pytest.raises(SystemExit) as exc_info:
            cli.main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "no product version requirements" in out.lower()
