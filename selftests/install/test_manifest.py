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


def test_pending_package_helpers():
    m = _sample_manifest()
    assert m.pending_packages_set() == {"libdrm"}
    m.add_pending_packages(["alsa-lib", "libdrm"])  # dedupe
    assert m.pending_packages_set() == {"libdrm", "alsa-lib"}
    m.claim_pending(["libdrm"], installed_at="2026-04-30T15:00:00Z", manager="dnf")
    assert m.pending_packages_set() == {"alsa-lib"}
    names = [it.name for it in m.items if isinstance(it, SystemPackageItem)]
    assert "libdrm" in names
