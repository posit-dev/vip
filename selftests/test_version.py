"""Tests for vip.version.ProductVersion."""

from __future__ import annotations

import pytest

from vip.version import ProductVersion


class TestParsing:
    def test_bare_version(self):
        v = ProductVersion("2026.06.0")
        assert (v.year, v.month, v.patch) == (2026, 6, 0)
        assert v.pre_kind is None
        assert v.pre_extra is None
        assert v.build is None

    def test_dev_suffix(self):
        v = ProductVersion("2026.06.0-dev")
        assert v.pre_kind == "dev"
        assert v.pre_extra is None

    def test_daily_suffix(self):
        v = ProductVersion("2026.06.0-daily.20260615")
        assert v.pre_kind == "daily"
        assert v.pre_extra == "20260615"

    def test_preview_suffix(self):
        v = ProductVersion("2026.06.0-preview")
        assert v.pre_kind == "preview"
        assert v.pre_extra is None

    def test_build_suffix(self):
        v = ProductVersion("2026.06.0+123")
        assert v.pre_kind is None
        assert v.build == "123"

    def test_dev_and_build_combo(self):
        v = ProductVersion("2026.06.0-dev+123")
        assert v.pre_kind == "dev"
        assert v.pre_extra is None
        assert v.build == "123"

    def test_daily_and_build_combo(self):
        v = ProductVersion("2026.06.0-daily.20260615+abc")
        assert v.pre_kind == "daily"
        assert v.pre_extra == "20260615"
        assert v.build == "abc"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "not-a-version",
            "2026.06",
            "2026.06.0.1",
            "2026.aa.0",
            "vX.Y.Z",
            "2026.06.0-rc1",  # unsupported pre-release kind
            "2026-06-0",
        ],
    )
    def test_malformed_raises(self, raw):
        with pytest.raises(ValueError, match="Cannot parse"):
            ProductVersion(raw)


class TestComparison:
    def test_equal_versions(self):
        assert ProductVersion("2026.06.0") == ProductVersion("2026.06.0")

    def test_not_equal_different_patch(self):
        assert ProductVersion("2026.06.0") != ProductVersion("2026.06.1")

    def test_year_month_patch_ordering(self):
        assert ProductVersion("2025.12.9") < ProductVersion("2026.01.0")
        assert ProductVersion("2026.05.0") < ProductVersion("2026.06.0")
        assert ProductVersion("2026.06.0") < ProductVersion("2026.06.1")

    def test_prerelease_sorts_before_release(self):
        release = ProductVersion("2026.06.0")
        for suffix in ("-dev", "-daily.20260615", "-preview"):
            pre = ProductVersion(f"2026.06.0{suffix}")
            assert pre < release, f"{pre} should sort before {release}"
            assert pre <= release
            assert release > pre
            assert release >= pre

    def test_prerelease_kind_ordering(self):
        dev = ProductVersion("2026.06.0-dev")
        daily = ProductVersion("2026.06.0-daily.20260615")
        preview = ProductVersion("2026.06.0-preview")
        assert dev < daily < preview

    def test_build_metadata_does_not_affect_ordering(self):
        assert ProductVersion("2026.06.0+123") == ProductVersion("2026.06.0+456")
        assert ProductVersion("2026.06.0+123") == ProductVersion("2026.06.0")

    def test_le_ge_operators(self):
        v1 = ProductVersion("2026.06.0")
        v2 = ProductVersion("2026.06.1")
        assert v1 <= v1
        assert v1 <= v2
        assert v2 >= v1
        assert v2 >= v2

    def test_comparison_with_non_product_version_not_implemented(self):
        v = ProductVersion("2026.06.0")
        assert (v == "2026.06.0") is False
        with pytest.raises(TypeError):
            v < "2026.06.0"  # noqa: B015


class TestHashability:
    def test_equal_versions_hash_equal(self):
        assert hash(ProductVersion("2026.06.0")) == hash(ProductVersion("2026.06.0"))

    def test_usable_as_dict_key(self):
        d = {ProductVersion("2026.06.0"): "shadcn"}
        assert d[ProductVersion("2026.06.0")] == "shadcn"

    def test_usable_in_set(self):
        s = {ProductVersion("2026.06.0"), ProductVersion("2026.06.0"), ProductVersion("2026.06.1")}
        assert len(s) == 2


class TestStrRepr:
    def test_str_preserves_original(self):
        assert str(ProductVersion("2026.06.0-dev+123")) == "2026.06.0-dev+123"

    def test_repr_is_informative(self):
        assert repr(ProductVersion("2026.06.0")) == "ProductVersion('2026.06.0')"
