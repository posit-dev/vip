"""Tests for src/vip/install/manifest.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vip.install.manifest import (
    SCHEMA_VERSION,
    Manifest,
    ManifestError,
    PlaywrightItem,
    SystemPackageItem,
    load,
    save,
)


def _sample_manifest() -> Manifest:
    return Manifest(
        version=SCHEMA_VERSION,
        vip_version="0.28.0",
        created_at="2026-04-30T14:22:11Z",
        updated_at="2026-04-30T14:22:11Z",
        host="rhel10-dev.example.com",
        platform="rhel-family",
        platform_id="rhel",
        platform_version="10",
        items=[
            SystemPackageItem(manager="dnf", name="nss", installed_at="2026-04-30T14:22:11Z"),
            PlaywrightItem(
                browser="chromium",
                cache_dir="/home/u/.cache/ms-playwright",
                installed_at="2026-04-30T14:22:11Z",
            ),
        ],
        pending_system_packages=["libdrm"],
    )


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / ".vip-install.json"
    m = _sample_manifest()
    save(m, path)
    loaded = load(path)
    assert loaded == m


def test_save_uses_atomic_write(tmp_path: Path):
    """The temp file must be replaced atomically; no .tmp left behind on success."""
    path = tmp_path / ".vip-install.json"
    save(_sample_manifest(), path)
    assert path.exists()
    assert not (tmp_path / ".vip-install.json.tmp").exists()


def test_load_missing_file_returns_none(tmp_path: Path):
    assert load(tmp_path / ".vip-install.json") is None


def test_load_empty_file_returns_none(tmp_path: Path):
    """Empty or whitespace-only manifest files should be treated as missing."""
    path = tmp_path / ".vip-install.json"
    path.write_text("")
    assert load(path) is None

    path.write_text("   \n  \t  ")
    assert load(path) is None


def test_load_corrupt_json_raises(tmp_path: Path):
    path = tmp_path / ".vip-install.json"
    path.write_text("{not json")
    with pytest.raises(ManifestError, match="corrupt"):
        load(path)


def test_load_unknown_schema_version_raises(tmp_path: Path):
    path = tmp_path / ".vip-install.json"
    path.write_text(json.dumps({"version": SCHEMA_VERSION + 1, "items": []}))
    with pytest.raises(ManifestError, match="newer"):
        load(path)


def test_save_writes_well_formed_json(tmp_path: Path):
    path = tmp_path / ".vip-install.json"
    save(_sample_manifest(), path)
    data = json.loads(path.read_text())
    assert data["version"] == SCHEMA_VERSION
    assert data["host"] == "rhel10-dev.example.com"
    assert data["pending_system_packages"] == ["libdrm"]
    assert {i["kind"] for i in data["items"]} == {"system_package", "playwright_browser"}


def test_save_cleans_up_tmp_on_write_failure(tmp_path: Path, monkeypatch):
    """If write_text raises, the .tmp file must not be left behind."""
    path = tmp_path / ".vip-install.json"
    tmp_path_expected = path.with_suffix(path.suffix + ".tmp")

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)

    with pytest.raises(OSError, match="disk full"):
        save(_sample_manifest(), path)

    assert not tmp_path_expected.exists()


def test_load_malformed_items_entry_missing_field_raises(tmp_path: Path):
    """A system_package item missing 'name' should raise ManifestError, not KeyError."""
    path = tmp_path / ".vip-install.json"
    item = {"kind": "system_package", "manager": "dnf", "installed_at": "2026-01-01T00:00:00Z"}
    data = {"version": SCHEMA_VERSION, "items": [item]}
    path.write_text(json.dumps(data))
    with pytest.raises(ManifestError, match="missing required field"):
        load(path)


def test_load_malformed_items_non_dict_entry_raises(tmp_path: Path):
    """A non-dict entry in 'items' should raise ManifestError, not AttributeError."""
    path = tmp_path / ".vip-install.json"
    data = {"version": SCHEMA_VERSION, "items": ["not-a-dict"]}
    path.write_text(json.dumps(data))
    with pytest.raises(ManifestError, match="is not an object"):
        load(path)


def test_load_items_not_a_list_raises(tmp_path: Path):
    """'items' field that is not an array should raise ManifestError."""
    path = tmp_path / ".vip-install.json"
    data = {"version": SCHEMA_VERSION, "items": 42}
    path.write_text(json.dumps(data))
    with pytest.raises(ManifestError, match="must be an array"):
        load(path)


def test_save_preserves_original_error_when_cleanup_fails(tmp_path: Path, monkeypatch):
    """If tmp.unlink itself fails, the original write error should still propagate."""
    real_write_text = Path.write_text
    real_unlink = Path.unlink

    def write_text_boom(self, *args, **kwargs):
        if self.name.endswith(".tmp"):
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    def unlink_boom(self, *args, **kwargs):
        if self.name.endswith(".tmp"):
            raise OSError("permission denied during cleanup")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text_boom)
    monkeypatch.setattr(Path, "unlink", unlink_boom)

    path = tmp_path / ".vip-install.json"
    with pytest.raises(OSError, match="disk full"):
        save(_sample_manifest(), path)


def test_load_pending_system_packages_not_a_list_raises(tmp_path):
    path = tmp_path / ".vip-install.json"
    path.write_text(
        json.dumps({"version": SCHEMA_VERSION, "items": [], "pending_system_packages": "abc"})
    )
    with pytest.raises(ManifestError, match="must be an array"):
        load(path)


def test_load_pending_system_packages_non_string_element_raises(tmp_path):
    path = tmp_path / ".vip-install.json"
    path.write_text(
        json.dumps({"version": SCHEMA_VERSION, "items": [], "pending_system_packages": ["nss", 42]})
    )
    with pytest.raises(ManifestError, match="must contain only strings"):
        load(path)


def test_manifest_round_trip_with_zypper_manager(tmp_path):
    """Manifest serialization must accept manager='zypper' as a valid value."""
    from vip.install.manifest import (
        SCHEMA_VERSION,
        Manifest,
        SystemPackageItem,
        load,
        save,
    )

    path = tmp_path / ".vip-install.json"
    m = Manifest(
        version=SCHEMA_VERSION,
        vip_version="0.0.0",
        created_at="t",
        updated_at="t",
        host="h",
        platform="suse-family",
        platform_id="opensuse-leap",
        platform_version="15.6",
        items=[
            SystemPackageItem(manager="zypper", name="mozilla-nss", installed_at="t1"),
        ],
        pending_system_packages=[],
    )
    save(m, path)
    loaded = load(path)
    assert loaded is not None
    assert loaded.platform == "suse-family"
    assert len(loaded.items) == 1
    assert loaded.items[0].manager == "zypper"
    assert loaded.items[0].name == "mozilla-nss"


def test_pending_package_helpers():
    m = _sample_manifest()
    assert m.pending_packages_set() == {"libdrm"}
    m.add_pending_packages(["alsa-lib", "libdrm"])  # dedupe
    assert m.pending_packages_set() == {"libdrm", "alsa-lib"}
    m.claim_pending([("libdrm", "libdrm")], installed_at="2026-04-30T15:00:00Z", manager="dnf")
    assert m.pending_packages_set() == {"alsa-lib"}
    names = [it.name for it in m.items if isinstance(it, SystemPackageItem)]
    assert "libdrm" in names


def test_claim_pending_records_concrete_name_not_alias():
    """#621: a pending alias (e.g. libcups2, resolved via dpkg Provides) is
    recorded under the concrete provider name, and the alias -- not the
    concrete name -- is what gets cleared from pending."""
    m = _sample_manifest()
    m.pending_system_packages = ["libcups2"]
    m.claim_pending(
        [("libcups2", "libcups2t64")], installed_at="2026-04-30T15:00:00Z", manager="apt"
    )
    assert m.pending_packages_set() == set()
    items = [it for it in m.items if isinstance(it, SystemPackageItem)]
    assert any(it.name == "libcups2t64" for it in items)
    assert not any(it.name == "libcups2" for it in items)


def test_claim_pending_ignores_unpending_alias():
    """A (pending_name, concrete_name) pair whose pending_name isn't actually
    pending is not claimed and doesn't create an item."""
    m = _sample_manifest()
    m.pending_system_packages = ["alsa-lib"]
    before_items = len(m.items)
    m.claim_pending(
        [("libcups2", "libcups2t64")], installed_at="2026-04-30T15:00:00Z", manager="apt"
    )
    assert m.pending_packages_set() == {"alsa-lib"}
    assert len(m.items) == before_items
