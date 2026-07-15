"""Tests for ``vip --version`` and ``vip --product-versions``."""

from __future__ import annotations

import sys

import pytest


class TestTargetedProductVersions:
    """The declared TARGETED_PRODUCT_VERSIONS constant."""

    def test_constant_is_a_nonempty_mapping(self):
        from vip.version import TARGETED_PRODUCT_VERSIONS

        assert isinstance(TARGETED_PRODUCT_VERSIONS, dict)
        assert TARGETED_PRODUCT_VERSIONS, "expected at least one targeted product"

    def test_values_parse_as_posit_calendar_versions(self):
        from vip.version import TARGETED_PRODUCT_VERSIONS, ProductVersion

        for product, version in TARGETED_PRODUCT_VERSIONS.items():
            # Raises ValueError if the declared version is malformed.
            ProductVersion(version)
            assert isinstance(product, str) and product


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
        assert __version__ in out
        assert out.strip() == f"vip {__version__}"

    def test_does_not_list_product_versions(self, capsys, monkeypatch):
        from vip.cli import main

        monkeypatch.setattr(sys, "argv", ["vip", "--version"])
        with pytest.raises(SystemExit):
            main()
        out = capsys.readouterr().out
        assert "connect" not in out.lower()


class TestProductVersionsFlag:
    """``vip --product-versions`` lists the targeted product versions."""

    def test_prints_each_targeted_product_and_exits(self, capsys, monkeypatch):
        from vip.cli import main
        from vip.version import TARGETED_PRODUCT_VERSIONS

        monkeypatch.setattr(sys, "argv", ["vip", "--product-versions"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        for product, version in TARGETED_PRODUCT_VERSIONS.items():
            assert product in out
            assert version in out
