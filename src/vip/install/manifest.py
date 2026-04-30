"""Read/write the per-project .vip-install.json manifest."""

from __future__ import annotations

import contextlib
import json
import os
import socket
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


class ManifestError(Exception):
    """Raised when the on-disk manifest can't be loaded safely."""


@dataclass
class SystemPackageItem:
    manager: str  # "dnf" | "apt"
    name: str
    installed_at: str
    kind: str = "system_package"


@dataclass
class PlaywrightItem:
    browser: str  # "chromium"
    cache_dir: str
    installed_at: str
    kind: str = "playwright_browser"


Item = SystemPackageItem | PlaywrightItem


@dataclass
class Manifest:
    version: int
    vip_version: str
    created_at: str
    updated_at: str
    host: str
    platform: str  # "rhel-family" | "debian-family" | "macos" | "unsupported"
    platform_id: str | None
    platform_version: str | None
    items: list[Item] = field(default_factory=list)
    pending_system_packages: list[str] = field(default_factory=list)

    def pending_packages_set(self) -> set[str]:
        return set(self.pending_system_packages)

    def add_pending_packages(self, names: Iterable[str]) -> None:
        existing = self.pending_packages_set()
        for n in names:
            if n not in existing:
                self.pending_system_packages.append(n)
                existing.add(n)

    def claim_pending(self, names: Iterable[str], *, installed_at: str, manager: str) -> None:
        names_set = set(names)
        for n in names_set:
            if n in self.pending_packages_set():
                self.items.append(
                    SystemPackageItem(manager=manager, name=n, installed_at=installed_at)
                )
        self.pending_system_packages = [
            p for p in self.pending_system_packages if p not in names_set
        ]


def default_path(project_root: Path | None = None) -> Path:
    return (project_root or Path.cwd()) / ".vip-install.json"


def current_host() -> str:
    return socket.gethostname()


def load(path: Path) -> Manifest | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ManifestError(
            f"Manifest at {path} is corrupt JSON ({exc}). Delete it manually to retry."
        ) from exc
    version = data.get("version")
    if not isinstance(version, int):
        raise ManifestError(f"Manifest at {path} is missing a numeric 'version' field.")
    if version > SCHEMA_VERSION:
        raise ManifestError(
            f"Manifest at {path} has version {version}, newer than this vip "
            f"({SCHEMA_VERSION}). Upgrade vip and try again."
        )
    items: list[Item] = []
    for idx, raw in enumerate(data.get("items", [])):
        if not isinstance(raw, dict):
            raise ManifestError(f"Manifest at {path} item {idx} is not an object: {raw!r}")
        kind = raw.get("kind")
        try:
            if kind == "system_package":
                items.append(
                    SystemPackageItem(
                        manager=raw["manager"],
                        name=raw["name"],
                        installed_at=raw["installed_at"],
                    )
                )
            elif kind == "playwright_browser":
                items.append(
                    PlaywrightItem(
                        browser=raw["browser"],
                        cache_dir=raw["cache_dir"],
                        installed_at=raw["installed_at"],
                    )
                )
            else:
                raise ManifestError(f"Manifest at {path} has unknown item kind {kind!r}.")
        except (KeyError, TypeError) as exc:
            raise ManifestError(
                f"Manifest at {path} item {idx} ({kind}) is missing required field: {exc}"
            ) from exc
    return Manifest(
        version=version,
        vip_version=data.get("vip_version", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        host=data.get("host", ""),
        platform=data.get("platform", "unsupported"),
        platform_id=data.get("platform_id"),
        platform_version=data.get("platform_version"),
        items=items,
        pending_system_packages=list(data.get("pending_system_packages", [])),
    )


def save(manifest: Manifest, path: Path) -> None:
    serialized = {
        "version": manifest.version,
        "vip_version": manifest.vip_version,
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
        "host": manifest.host,
        "platform": manifest.platform,
        "platform_id": manifest.platform_id,
        "platform_version": manifest.platform_version,
        "items": [_serialize_item(i) for i in manifest.items],
        "pending_system_packages": list(manifest.pending_system_packages),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(serialized, indent=2, sort_keys=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def _serialize_item(item: Item) -> dict:
    if isinstance(item, SystemPackageItem):
        return {
            "kind": "system_package",
            "manager": item.manager,
            "name": item.name,
            "installed_at": item.installed_at,
        }
    if isinstance(item, PlaywrightItem):
        return {
            "kind": "playwright_browser",
            "browser": item.browser,
            "cache_dir": item.cache_dir,
            "installed_at": item.installed_at,
        }
    raise TypeError(f"Unknown item type: {type(item).__name__}")
