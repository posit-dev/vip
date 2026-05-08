# Mac and openSUSE CI Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend VIP's CI to run selftests and the headless Chromium smoke test on macOS and openSUSE Leap, alongside existing Ubuntu and RHEL coverage.

**Architecture:** Add a third platform family `suse-family` (zypper) to `src/vip/install/`. Generalize the existing RHEL smoke script into a single `docker/playwright-smoke.py` reused by all three Linux Dockerfiles and the new macOS smoke job. Extend `ci.yml`'s selftest matrix to `macos-latest`, rename `rhel-smoke.yml` to `linux-smoke.yml` with an `opensuse-leap` matrix entry, and add a new `mac-smoke.yml`.

**Tech Stack:** Python 3.10+/3.12 (`uv`-managed), `pytest_bdd`, Playwright (Chromium), Docker buildx, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-05-08-mac-opensuse-ci-design.md`

---

## File Structure

**Modify:**
- `src/vip/install/platform.py` — add `suse-family` detection + `SUSE_PACKAGES` + review constant
- `src/vip/install/plan.py` — add `suse-family` branch in `build_install_plan` + zypper remove command in `build_uninstall_plan`
- `src/vip/install/runner.py` — handle `manager == "zypper"` in three places
- `src/vip/install/manifest.py` — update one docstring comment
- `selftests/install/test_platform.py` — add suse-family detection cases
- `selftests/install/test_plan.py` — add suse-family install/uninstall plan cases
- `selftests/install/test_runner.py` — add zypper format/execute cases
- `selftests/install/test_manifest.py` — add zypper round-trip
- `docker/rhel9/Dockerfile`, `docker/rhel10/Dockerfile` — point CMD at renamed script
- `.github/workflows/ci.yml` — extend selftest matrix to macOS
- `justfile` — add `opensuse-leap-smoke` recipe (mirrors `rhel9-smoke`)

**Create:**
- `docker/opensuse-leap/Dockerfile`
- `.github/workflows/mac-smoke.yml`

**Rename:**
- `docker/rhel-smoke.py` → `docker/playwright-smoke.py`
- `.github/workflows/rhel-smoke.yml` → `.github/workflows/linux-smoke.yml`

**Delete after implementation:**
- `docs/superpowers/specs/2026-05-08-mac-opensuse-ci-design.md`

---

## Task 1: Add SUSE family detection to `platform.py`

**Files:**
- Modify: `src/vip/install/platform.py:11-13` (add `_SUSE_LIKE`), `src/vip/install/platform.py:38-44` (add suse branch)
- Test: `selftests/install/test_platform.py`

- [ ] **Step 1: Write the failing tests**

Add these test cases to `selftests/install/test_platform.py` after `test_detect_popos_via_id_like` (around line 89):

```python
def test_detect_opensuse_leap(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release(
        'ID="opensuse-leap"\nVERSION_ID="15.6"\nID_LIKE="suse opensuse"\n'
    )
    info = plat.detect()
    assert info.family == "suse-family"
    assert info.id == "opensuse-leap"
    assert info.version == "15.6"


def test_detect_opensuse_tumbleweed(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release(
        'ID="opensuse-tumbleweed"\nVERSION_ID="20260101"\nID_LIKE="opensuse suse"\n'
    )
    info = plat.detect()
    assert info.family == "suse-family"


def test_detect_sles(monkeypatch, fake_os_release):
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="sles"\nVERSION_ID="15.5"\nID_LIKE="suse"\n')
    info = plat.detect()
    assert info.family == "suse-family"


def test_detect_suse_via_id_like_only(monkeypatch, fake_os_release):
    """A SUSE-derivative whose ID is something else should still route to suse-family."""
    monkeypatch.setattr(plat.sys, "platform", "linux")
    fake_os_release('ID="microos"\nID_LIKE="suse opensuse"\nVERSION_ID="6"\n')
    info = plat.detect()
    assert info.family == "suse-family"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/install/test_platform.py -v -k opensuse or sles or suse_via`
Expected: 4 FAIL with `assert 'unsupported' == 'suse-family'`

- [ ] **Step 3: Update `src/vip/install/platform.py`**

Replace lines 11-13:

```python
_OS_RELEASE_PATH = Path("/etc/os-release")

_RHEL_LIKE = {"rhel", "fedora", "centos", "rocky", "almalinux", "ol"}
_DEBIAN_LIKE = {"debian", "ubuntu"}
```

with:

```python
_OS_RELEASE_PATH = Path("/etc/os-release")

_RHEL_LIKE = {"rhel", "fedora", "centos", "rocky", "almalinux", "ol"}
_DEBIAN_LIKE = {"debian", "ubuntu"}
_SUSE_LIKE = {"opensuse-leap", "opensuse-tumbleweed", "sles", "suse", "opensuse"}
```

Replace lines 38-44:

```python
    candidates = {distro_id, *id_like}
    family = "unsupported"
    if candidates & _RHEL_LIKE:
        family = "rhel-family"
    elif candidates & _DEBIAN_LIKE:
        family = "debian-family"
    return PlatformInfo(family=family, id=distro_id or None, version=version, raw=raw)
```

with:

```python
    candidates = {distro_id, *id_like}
    family = "unsupported"
    if candidates & _RHEL_LIKE:
        family = "rhel-family"
    elif candidates & _DEBIAN_LIKE:
        family = "debian-family"
    elif candidates & _SUSE_LIKE:
        family = "suse-family"
    return PlatformInfo(family=family, id=distro_id or None, version=version, raw=raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/install/test_platform.py -v`
Expected: All tests pass (existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add src/vip/install/platform.py selftests/install/test_platform.py
git commit -m "feat(install): detect openSUSE/SLES as suse-family"
```

---

## Task 2: Add `SUSE_PACKAGES` tuple and parity review constant

**Files:**
- Modify: `src/vip/install/platform.py:91-118` (after `DEBIAN_PACKAGES`)
- Test: `selftests/install/test_platform.py`

- [ ] **Step 1: Write the failing tests**

Add to `selftests/install/test_platform.py` after `test_debian_packages_is_tuple_of_strings`:

```python
def test_suse_packages_is_tuple_of_strings():
    assert isinstance(plat.SUSE_PACKAGES, tuple)
    assert all(isinstance(p, str) and p for p in plat.SUSE_PACKAGES)
    # Spot check: zypper-named Chromium runtime libs.
    assert "mozilla-nss" in plat.SUSE_PACKAGES
    assert "libdrm2" in plat.SUSE_PACKAGES


def test_list_reviewed_against_playwright_suse_matches_pinned_version():
    """Reminds maintainer to review SUSE_PACKAGES when playwright is bumped."""
    import sys

    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore[no-redef]

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    pw_dep = next(d for d in deps if d.startswith("playwright"))
    pinned = pw_dep.split(">=", 1)[1].split(",", 1)[0].strip()
    reviewed = plat.LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE
    nativedeps_url = (
        "https://github.com/microsoft/playwright/blob/main"
        "/packages/playwright-core/src/server/registry/nativeDeps.ts"
    )
    assert reviewed == pinned, (
        f"SUSE_PACKAGES was last reviewed for playwright {reviewed}, "
        f"but pyproject.toml now pins playwright {pinned}. "
        f"Review src/vip/install/platform.py:SUSE_PACKAGES against {nativedeps_url} "
        "and bump LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE to match."
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/install/test_platform.py -v -k suse_packages or reviewed_against_playwright_suse`
Expected: 2 FAIL with `AttributeError: module 'vip.install.platform' has no attribute 'SUSE_PACKAGES'` (and similar for the constant).

- [ ] **Step 3: Add the package list and constant to `src/vip/install/platform.py`**

Append after the existing `LIST_REVIEWED_AGAINST_PLAYWRIGHT = "1.40"` line (around line 118):

```python


# openSUSE/SLES equivalents. Names from `zypper search --provides` against
# opensuse/leap:15. Bump LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE after each
# playwright pin update; the selftest enforces parity.
SUSE_PACKAGES: tuple[str, ...] = (
    "mozilla-nss",
    "mozilla-nspr",
    "libatk-1_0-0",
    "libatk-bridge-2_0-0",
    "libcups2",
    "libdrm2",
    "libxkbcommon0",
    "libxcomposite1",
    "libxdamage1",
    "libxfixes3",
    "libxrandr2",
    "libgbm1",
    "libpango-1_0-0",
    "libcairo2",
    "libasound2",
    "libxshmfence1",
    "libX11-6",
    "libxcb1",
    "libxext6",
    "libdbus-1-3",
    "libglib-2_0-0",
)

# Mirror of LIST_REVIEWED_AGAINST_PLAYWRIGHT for the SUSE list.
LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE = "1.40"
```

The value `"1.40"` matches the existing `LIST_REVIEWED_AGAINST_PLAYWRIGHT` so both selftests stay green together.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/install/test_platform.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/vip/install/platform.py selftests/install/test_platform.py
git commit -m "feat(install): add SUSE Chromium runtime package list"
```

---

## Task 3: Add `suse-family` branch to `build_install_plan`

**Files:**
- Modify: `src/vip/install/plan.py:62-81` (the family-branching block in `build_install_plan`)
- Test: `selftests/install/test_plan.py`

- [ ] **Step 1: Write the failing test**

Add to `selftests/install/test_plan.py` after `test_install_plan_debian_uses_apt`:

```python
def test_install_plan_suse_uses_zypper(tmp_path: Path):
    info = PlatformInfo(family="suse-family", id="opensuse-leap", version="15.6")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: set(),
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is not None
    assert plan.system_step.manager == "zypper"
    assert "mozilla-nss" in plan.system_step.packages
    assert plan.playwright_step is not None


def test_install_plan_suse_uses_rpm_for_present_check(tmp_path: Path):
    """openSUSE uses rpm under the hood, so rpm_installed must be the lookup."""
    info = PlatformInfo(family="suse-family", id="opensuse-leap", version="15.6")
    plan = pl.build_install_plan(
        platform_info=info,
        manifest=None,
        rpm_installed=lambda names: {"mozilla-nss", "libdrm2"},
        dpkg_installed=lambda names: set(),
        chromium_present=False,
        playwright_cache_dir=tmp_path / "cache",
        skip_system=False,
    )
    assert plan.system_step is not None
    assert "mozilla-nss" not in plan.system_step.packages
    assert "libdrm2" not in plan.system_step.packages
    assert "libcups2" in plan.system_step.packages
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/install/test_plan.py -v -k suse`
Expected: 2 FAIL — `assert plan.system_step is not None` (it's None because suse-family falls through to neither rhel nor debian branch).

- [ ] **Step 3: Update `src/vip/install/plan.py`**

In `build_install_plan`, change lines 63-72 from:

```python
        if family == "rhel-family":
            present = rpm_installed(plat.RHEL_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.RHEL_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="dnf", packages=missing)
        elif family == "debian-family":
            present = dpkg_installed(plat.DEBIAN_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.DEBIAN_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="apt", packages=missing)
```

to:

```python
        if family == "rhel-family":
            present = rpm_installed(plat.RHEL_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.RHEL_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="dnf", packages=missing)
        elif family == "debian-family":
            present = dpkg_installed(plat.DEBIAN_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.DEBIAN_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="apt", packages=missing)
        elif family == "suse-family":
            present = rpm_installed(plat.SUSE_PACKAGES)
            claim_pending = tuple(sorted(pending & present))
            missing = tuple(p for p in plat.SUSE_PACKAGES if p not in present)
            system_step = SystemPackagesStep(manager="zypper", packages=missing)
```

Also update the comment on `SystemPackagesStep.manager` at `src/vip/install/plan.py:15`:

```python
class SystemPackagesStep:
    manager: str  # "dnf" | "apt"
    packages: tuple[str, ...]
```

to:

```python
class SystemPackagesStep:
    manager: str  # "dnf" | "apt" | "zypper"
    packages: tuple[str, ...]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest selftests/install/test_plan.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/vip/install/plan.py selftests/install/test_plan.py
git commit -m "feat(install): build install plan for suse-family with zypper manager"
```

---

## Task 4: Handle `manager == "zypper"` in `runner.py`

**Files:**
- Modify: `src/vip/install/runner.py:34-58` (`format_install_plan`), `src/vip/install/runner.py:80-98` (`execute_install_plan` non-root branch and root branch), `src/vip/install/runner.py:116-128` (`_manager_for`, `_install_system_packages`)
- Test: `selftests/install/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Add to `selftests/install/test_runner.py` after `test_format_install_plan_with_packages_and_browser`:

```python
def test_format_install_plan_with_zypper_packages(tmp_path: Path):
    plan = InstallPlan(
        platform="suse-family",
        platform_id="opensuse-leap",
        platform_version="15.6",
        system_step=SystemPackagesStep(
            manager="zypper", packages=("mozilla-nss", "libdrm2")
        ),
        playwright_step=PlaywrightStep(browser="chromium", cache_dir=str(tmp_path)),
    )
    text = rn.format_install_plan(plan)
    assert "mozilla-nss" in text and "libdrm2" in text
    assert "sudo zypper install -y" in text


def test_execute_install_plan_zypper_non_root_writes_pending(monkeypatch, tmp_path: Path):
    plan = InstallPlan(
        platform="suse-family",
        platform_id="opensuse-leap",
        platform_version="15.6",
        system_step=SystemPackagesStep(
            manager="zypper", packages=("mozilla-nss", "libdrm2")
        ),
        playwright_step=None,
    )
    monkeypatch.setattr(rn, "is_root", lambda: False)
    manifest_path = tmp_path / ".vip-install.json"
    manifest = Manifest(
        version=SCHEMA_VERSION,
        vip_version="0.0.0",
        created_at="t",
        updated_at="t",
        host="h",
        platform="suse-family",
        platform_id="opensuse-leap",
        platform_version="15.6",
    )
    rc = rn.execute_install_plan(plan, manifest=manifest, manifest_path=manifest_path)
    assert rc == 2
    from vip.install.manifest import load
    saved = load(manifest_path)
    assert set(saved.pending_system_packages) == {"mozilla-nss", "libdrm2"}


def test_install_system_packages_zypper_invokes_correct_command(monkeypatch):
    captured = []
    def fake_run(args, check):
        captured.append(args)
        return None
    monkeypatch.setattr(rn.subprocess, "run", fake_run)
    rn._install_system_packages("zypper", ("mozilla-nss", "libdrm2"))
    assert captured == [
        ["zypper", "install", "-y", "--no-confirm", "mozilla-nss", "libdrm2"]
    ]


def test_manager_for_suse_family():
    assert rn._manager_for("suse-family") == "zypper"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest selftests/install/test_runner.py -v -k zypper or manager_for_suse`
Expected: 4 FAIL — for example, `test_format_install_plan_with_zypper_packages` fails because the format string falls through to the apt branch (`sudo apt install`).

- [ ] **Step 3: Update `format_install_plan` in `src/vip/install/runner.py`**

Replace lines 44-48 (inside `format_install_plan`) from:

```python
    if plan.system_step and plan.system_step.packages:
        manager = plan.system_step.manager
        cmd = "sudo dnf install -y" if manager == "dnf" else "sudo apt install -y"
        lines.append("  system packages to install (run yourself if not root):")
        lines.append(f"    {cmd} {' '.join(plan.system_step.packages)}")
```

to:

```python
    if plan.system_step and plan.system_step.packages:
        manager = plan.system_step.manager
        if manager == "dnf":
            cmd = "sudo dnf install -y"
        elif manager == "zypper":
            cmd = "sudo zypper install -y"
        else:
            cmd = "sudo apt install -y"
        lines.append("  system packages to install (run yourself if not root):")
        lines.append(f"    {cmd} {' '.join(plan.system_step.packages)}")
```

- [ ] **Step 4: Update `execute_install_plan` non-root message**

In `execute_install_plan`, replace lines 80-86 from:

```python
    if needs_root and system_step is not None and not is_root():
        manifest.add_pending_packages(system_step.packages)
        manifest.updated_at = now
        save(manifest, manifest_path)
        cmd = "sudo dnf install -y" if system_step.manager == "dnf" else "sudo apt install -y"
        print(f"\nNot running as root. Please run:\n  {cmd} {' '.join(system_step.packages)}")
        print("Then re-run `vip install`.")
```

to:

```python
    if needs_root and system_step is not None and not is_root():
        manifest.add_pending_packages(system_step.packages)
        manifest.updated_at = now
        save(manifest, manifest_path)
        if system_step.manager == "dnf":
            cmd = "sudo dnf install -y"
        elif system_step.manager == "zypper":
            cmd = "sudo zypper install -y"
        else:
            cmd = "sudo apt install -y"
        print(f"\nNot running as root. Please run:\n  {cmd} {' '.join(system_step.packages)}")
        print("Then re-run `vip install`.")
```

- [ ] **Step 5: Update `_manager_for`**

Replace `_manager_for` (line 116-117) from:

```python
def _manager_for(platform_family: str) -> str:
    return "dnf" if platform_family == "rhel-family" else "apt"
```

to:

```python
def _manager_for(platform_family: str) -> str:
    if platform_family == "rhel-family":
        return "dnf"
    if platform_family == "suse-family":
        return "zypper"
    return "apt"
```

- [ ] **Step 6: Update `_install_system_packages`**

Replace `_install_system_packages` (lines 120-128) from:

```python
def _install_system_packages(manager: str, packages: tuple[str, ...]) -> None:
    if not packages:
        return
    if manager == "dnf":
        subprocess.run(["dnf", "install", "-y", *packages], check=True)
    elif manager == "apt":
        subprocess.run(["apt", "install", "-y", *packages], check=True)
    else:
        raise ValueError(f"Unknown manager {manager!r}")
```

to:

```python
def _install_system_packages(manager: str, packages: tuple[str, ...]) -> None:
    if not packages:
        return
    if manager == "dnf":
        subprocess.run(["dnf", "install", "-y", *packages], check=True)
    elif manager == "apt":
        subprocess.run(["apt", "install", "-y", *packages], check=True)
    elif manager == "zypper":
        subprocess.run(
            ["zypper", "install", "-y", "--no-confirm", *packages], check=True
        )
    else:
        raise ValueError(f"Unknown manager {manager!r}")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest selftests/install/test_runner.py -v`
Expected: All tests pass (existing + 4 new).

- [ ] **Step 8: Commit**

```bash
git add src/vip/install/runner.py selftests/install/test_runner.py
git commit -m "feat(install): execute install plan via zypper on suse-family"
```

---

## Task 5: Add zypper remove command to `build_uninstall_plan`

**Files:**
- Modify: `src/vip/install/plan.py:120-128` (the manager-to-command mapping in `build_uninstall_plan`)
- Test: `selftests/install/test_plan.py`

- [ ] **Step 1: Write the failing test**

Add to `selftests/install/test_plan.py` after `test_uninstall_plan_emits_command_per_manager_when_mixed`:

```python
def test_uninstall_plan_emits_zypper_command():
    m = _empty_manifest(family="suse-family")
    m.platform_id = "opensuse-leap"
    m.platform_version = "15.6"
    m.items = [
        SystemPackageItem(manager="zypper", name="mozilla-nss", installed_at="t"),
        SystemPackageItem(manager="zypper", name="libdrm2", installed_at="t"),
    ]
    plan = pl.build_uninstall_plan(manifest=m, connect_url=None)
    assert plan.system_remove_commands == ("sudo zypper remove libdrm2 mozilla-nss",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest selftests/install/test_plan.py -v -k zypper`
Expected: FAIL — `assert () == ('sudo zypper remove libdrm2 mozilla-nss',)` (no command emitted because the unknown-manager branch silently skips).

- [ ] **Step 3: Update `build_uninstall_plan` in `src/vip/install/plan.py`**

Replace lines 121-128 from:

```python
    for manager, names in sorted(by_manager_tuples.items()):
        if not names:
            continue
        if manager == "dnf":
            commands.append("sudo dnf remove " + " ".join(names))
        elif manager == "apt":
            commands.append("sudo apt remove --autoremove " + " ".join(names))
        # Unknown manager: skip (we don't know how to remove)
```

to:

```python
    for manager, names in sorted(by_manager_tuples.items()):
        if not names:
            continue
        if manager == "dnf":
            commands.append("sudo dnf remove " + " ".join(names))
        elif manager == "apt":
            commands.append("sudo apt remove --autoremove " + " ".join(names))
        elif manager == "zypper":
            commands.append("sudo zypper remove " + " ".join(names))
        # Unknown manager: skip (we don't know how to remove)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest selftests/install/test_plan.py -v -k zypper`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/vip/install/plan.py selftests/install/test_plan.py
git commit -m "feat(install): emit zypper remove command for suse-family uninstall"
```

---

## Task 6: Update manifest comment to mention `suse-family`

**Files:**
- Modify: `src/vip/install/manifest.py:46`
- Test: `selftests/install/test_manifest.py`

- [ ] **Step 1: Write the failing test**

Add to `selftests/install/test_manifest.py` (find the test that round-trips `SystemPackageItem` and add a parallel one):

```python
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
```

- [ ] **Step 2: Run test to verify it passes (manifest already supports any string)**

Run: `uv run pytest selftests/install/test_manifest.py::test_manifest_round_trip_with_zypper_manager -v`
Expected: PASS — `manager` is a free-form string field; no schema change needed. The selftest just pins this expectation.

- [ ] **Step 3: Update the docstring comment in `src/vip/install/manifest.py`**

Replace line 22:

```python
    manager: str  # "dnf" | "apt"
```

with:

```python
    manager: str  # "dnf" | "apt" | "zypper"
```

And replace line 46:

```python
    platform: str  # "rhel-family" | "debian-family" | "macos" | "unsupported"
```

with:

```python
    platform: str  # "rhel-family" | "debian-family" | "suse-family" | "macos" | "unsupported"
```

- [ ] **Step 4: Run all install selftests to confirm nothing regressed**

Run: `uv run pytest selftests/install/ -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/vip/install/manifest.py selftests/install/test_manifest.py
git commit -m "docs(install): document zypper and suse-family in manifest type comments"
```

---

## Task 7: Run full lint/format checks before moving to Docker/CI

**Files:** None (verification only)

- [ ] **Step 1: Run lint**

Run: `uv run ruff check src/ selftests/ examples/ docker/`
Expected: All checks passed.

- [ ] **Step 2: Run format check**

Run: `uv run ruff format --check src/ selftests/ examples/ docker/`
Expected: All files formatted.

- [ ] **Step 3: Run typecheck**

Run: `uv run mypy src/vip/`
Expected: Success.

- [ ] **Step 4: Run all selftests one more time**

Run: `uv run pytest selftests/ -v`
Expected: All tests pass.

If any step fails, fix before continuing — do not commit.

---

## Task 8: Rename `docker/rhel-smoke.py` to `docker/playwright-smoke.py` with a generic platform label

**Files:**
- Rename: `docker/rhel-smoke.py` → `docker/playwright-smoke.py`
- Modify: the renamed file's `_rhel_major_version` → `_platform_label`

- [ ] **Step 1: Rename the file (preserving git history)**

Run: `git mv docker/rhel-smoke.py docker/playwright-smoke.py`
Expected: The file moves; `git status` shows the rename.

- [ ] **Step 2: Replace the contents of `docker/playwright-smoke.py`**

Overwrite the file with:

```python
"""Headless Chromium smoke test usable on any vip-supported platform.

Mirrors microsoft/playwright#40312's manual test: launches Chromium
headlessly, exercises basic page interaction and JS evaluation, and
takes a screenshot. Exits non-zero on any failure so docker run /
the GitHub Actions step propagates the result.
"""

import platform as _stdplatform
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def _platform_label() -> str:
    """Best-effort short label like 'rhel9', 'leap15', 'macos-14.5', or 'unknown'."""
    if sys.platform == "darwin":
        ver = _stdplatform.mac_ver()[0] or "unknown"
        return f"macos-{ver}"
    try:
        text = Path("/etc/os-release").read_text()
    except OSError:
        return "unknown"
    distro_id = ""
    version_major = ""
    m_id = re.search(r'^ID="?([^"\n]+)"?', text, re.MULTILINE)
    if m_id:
        distro_id = m_id.group(1).strip()
    m_ver = re.search(r'^VERSION_ID="?(\d+)', text, re.MULTILINE)
    if m_ver:
        version_major = m_ver.group(1)
    label = f"{distro_id}{version_major}".strip()
    return label or "unknown"


def main() -> None:
    label = _platform_label()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(
            "data:text/html,<title>vip smoke</title><h1 id=h>ok</h1><input id=i><div id=r></div>"
        )
        title = page.title()
        if title != "vip smoke":
            raise RuntimeError(f"unexpected title: {title!r}")
        page.fill("#i", f"hello from {label}")
        page.evaluate(
            "document.getElementById('r').textContent = document.getElementById('i').value"
        )
        text = page.text_content("#r")
        if text != f"hello from {label}":
            raise RuntimeError(f"unexpected DOM text: {text!r}")
        ua = page.evaluate("navigator.userAgent")
        if "HeadlessChrome" not in ua:
            raise RuntimeError(f"unexpected UA: {ua!r}")
        page.screenshot(path="/tmp/smoke.png")
        browser.close()
    print(f"PASS: {label} headless chromium smoke")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run lint and format**

Run these commands:

```bash
uv run ruff check docker/playwright-smoke.py
uv run ruff format --check docker/playwright-smoke.py
```
Expected: Both pass.

- [ ] **Step 4: Sanity-check it imports clean**

Run: `uv run python -c "import importlib.util, pathlib; spec = importlib.util.spec_from_file_location('s', pathlib.Path('docker/playwright-smoke.py')); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m._platform_label())"`
Expected: prints e.g. `macos-15.0` (when run from a Mac dev machine) or `unknown` (when /etc/os-release is missing).

- [ ] **Step 5: Commit**

```bash
git add docker/playwright-smoke.py docker/rhel-smoke.py
git commit -m "refactor(docker): rename rhel-smoke.py to playwright-smoke.py for cross-platform use"
```

---

## Task 9: Update RHEL Dockerfiles to invoke the renamed smoke script

**Files:**
- Modify: `docker/rhel9/Dockerfile:23`, `docker/rhel10/Dockerfile:23`

- [ ] **Step 1: Update `docker/rhel9/Dockerfile` CMD line**

Replace line 23:

```dockerfile
CMD ["uv", "run", "python", "/app/docker/rhel-smoke.py"]
```

with:

```dockerfile
CMD ["uv", "run", "python", "/app/docker/playwright-smoke.py"]
```

- [ ] **Step 2: Update `docker/rhel10/Dockerfile` CMD line**

Replace line 23:

```dockerfile
CMD ["uv", "run", "python", "/app/docker/rhel-smoke.py"]
```

with:

```dockerfile
CMD ["uv", "run", "python", "/app/docker/playwright-smoke.py"]
```

- [ ] **Step 3: Commit**

```bash
git add docker/rhel9/Dockerfile docker/rhel10/Dockerfile
git commit -m "refactor(docker): point RHEL Dockerfiles at playwright-smoke.py"
```

---

## Task 10: Create `docker/opensuse-leap/Dockerfile`

**Files:**
- Create: `docker/opensuse-leap/Dockerfile`

- [ ] **Step 1: Create the directory and Dockerfile**

Run: `mkdir -p docker/opensuse-leap`

Then create `docker/opensuse-leap/Dockerfile` with this content:

```dockerfile
# openSUSE Leap headless Chromium smoke test image
# See docs/superpowers/specs/2026-05-08-mac-opensuse-ci-design.md
FROM opensuse/leap:15

# python312 is required by vip's pyproject.toml. procps provides ps.
# gzip and tar are needed for the uv tarball extraction in the COPY --from below.
RUN zypper -n install \
        python312 python312-pip procps gzip tar \
    && zypper clean --all

# Install uv (matches version pinned in vip's main Dockerfiles)
COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

# Sync vip's Python dependencies. Frozen lockfile reproduces CI exactly.
RUN uv sync --frozen

# Install Chromium runtime libs (via zypper) and the Playwright browser bundle via vip.
# Runs as root inside Docker, so vip install invokes zypper directly.
RUN uv run vip install

CMD ["uv", "run", "python", "/app/docker/playwright-smoke.py"]
```

- [ ] **Step 2: Build the image locally to verify it works**

Run: `docker build --platform linux/amd64 -f docker/opensuse-leap/Dockerfile -t vip-opensuse-leap-smoke .`
Expected: Build completes; final image tagged `vip-opensuse-leap-smoke`.

If `python312` is not found in the openSUSE Leap 15.x repos, fall back to `python311` (and update `pyproject.toml`'s required-python expression check by re-running `uv sync` to confirm it still installs). Document any such fallback in the commit message.

- [ ] **Step 3: Run the image to verify the smoke succeeds**

Run: `docker run --rm --platform linux/amd64 vip-opensuse-leap-smoke`
Expected: prints `PASS: opensuse-leap15 headless chromium smoke` and exits 0.

- [ ] **Step 4: Commit**

```bash
git add docker/opensuse-leap/Dockerfile
git commit -m "feat(docker): add openSUSE Leap headless Chromium smoke image"
```

---

## Task 11: Add `opensuse-leap-smoke` recipe to `justfile` and update `scripts/rhel-smoke.sh` (or add a sibling)

**Files:**
- Modify: `justfile:106-112` (existing `rhel9-smoke` / `rhel10-smoke` recipes — append a sibling)
- Create: `scripts/opensuse-leap-smoke.sh`

- [ ] **Step 1: Create `scripts/opensuse-leap-smoke.sh`**

This mirrors `scripts/rhel-smoke.sh` but is single-version, so it doesn't need a positional argument:

```bash
#!/usr/bin/env bash
# Build and run the openSUSE Leap headless Chromium smoke test.
# Usage: ./scripts/opensuse-leap-smoke.sh
set -euo pipefail

docker build --platform linux/amd64 \
    -f "docker/opensuse-leap/Dockerfile" \
    -t "vip-opensuse-leap-smoke" .
docker run --rm --platform linux/amd64 "vip-opensuse-leap-smoke"

echo "==> verifying vip install --dry-run reports nothing to install"
docker run --rm --platform linux/amd64 "vip-opensuse-leap-smoke" \
    /bin/sh -c 'uv run vip install --dry-run | grep -q "nothing to install"'

echo "==> verifying vip uninstall --yes runs cleanly"
docker run --rm --platform linux/amd64 "vip-opensuse-leap-smoke" \
    /bin/sh -c 'uv run vip uninstall --yes | tee /tmp/uninst.log; \
                grep -q "vip uninstall: complete" /tmp/uninst.log'
```

Then make it executable:

Run: `chmod +x scripts/opensuse-leap-smoke.sh`

- [ ] **Step 2: Append a `just` recipe**

Append to `justfile` (after line 112, the `rhel10-smoke` recipe):

```
# Build and run the openSUSE Leap headless Chromium smoke test
opensuse-leap-smoke:
    ./scripts/opensuse-leap-smoke.sh
```

- [ ] **Step 3: Verify by running it locally**

Run: `just opensuse-leap-smoke`
Expected: prints the smoke PASS line, then `nothing to install`, then `vip uninstall: complete`.

- [ ] **Step 4: Commit**

```bash
git add justfile scripts/opensuse-leap-smoke.sh
git commit -m "build(just): add opensuse-leap-smoke recipe"
```

---

## Task 12: Rename `rhel-smoke.yml` to `linux-smoke.yml` and add `opensuse-leap` to the matrix

**Files:**
- Rename: `.github/workflows/rhel-smoke.yml` → `.github/workflows/linux-smoke.yml`
- Modify: workflow `name`, `paths` filters, and matrix `version` list

- [ ] **Step 1: Rename the workflow file**

Run: `git mv .github/workflows/rhel-smoke.yml .github/workflows/linux-smoke.yml`
Expected: File moves; `git status` shows the rename.

- [ ] **Step 2: Replace contents with the extended workflow**

Overwrite `.github/workflows/linux-smoke.yml` with:

```yaml
name: Linux Smoke

on:
  push:
    branches: [main]
    paths:
      - 'docker/rhel*/**'
      - 'docker/opensuse-leap/**'
      - 'docker/playwright-smoke.py'
      - 'scripts/rhel-smoke.sh'
      - 'scripts/opensuse-leap-smoke.sh'
      - 'justfile'
      - 'pyproject.toml'
      - 'uv.lock'
      - 'src/**'
      - 'selftests/**'
      - '.github/workflows/linux-smoke.yml'
  pull_request:
    paths:
      - 'docker/rhel*/**'
      - 'docker/opensuse-leap/**'
      - 'docker/playwright-smoke.py'
      - 'scripts/rhel-smoke.sh'
      - 'scripts/opensuse-leap-smoke.sh'
      - 'justfile'
      - 'pyproject.toml'
      - 'uv.lock'
      - 'src/**'
      - 'selftests/**'
      - '.github/workflows/linux-smoke.yml'

jobs:
  smoke:
    name: ${{ matrix.version }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        version: [rhel9, rhel10, opensuse-leap]
    steps:
      - uses: actions/checkout@v6

      - uses: docker/setup-buildx-action@v3

      - name: Cache Docker layers
        uses: actions/cache@v4
        with:
          path: /tmp/.buildx-cache
          key: ${{ runner.os }}-buildx-${{ matrix.version }}-${{ hashFiles(format('docker/{0}/Dockerfile', matrix.version), 'pyproject.toml', 'uv.lock') }}
          restore-keys: |
            ${{ runner.os }}-buildx-${{ matrix.version }}-

      - name: Build smoke image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/${{ matrix.version }}/Dockerfile
          platforms: linux/amd64
          load: true
          tags: vip-${{ matrix.version }}-smoke
          cache-from: type=local,src=/tmp/.buildx-cache
          cache-to: type=local,dest=/tmp/.buildx-cache-new,mode=max

      - name: Move cache
        run: |
          rm -rf /tmp/.buildx-cache
          mv /tmp/.buildx-cache-new /tmp/.buildx-cache

      - name: Run smoke
        run: docker run --rm --platform linux/amd64 vip-${{ matrix.version }}-smoke
```

- [ ] **Step 3: Validate the YAML locally**

Run: `uv run python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/linux-smoke.yml').read_text()); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/linux-smoke.yml .github/workflows/rhel-smoke.yml
git commit -m "ci: rename rhel-smoke to linux-smoke and add opensuse-leap matrix entry"
```

---

## Task 13: Add `macos-latest` to the `ci.yml` selftest matrix

**Files:**
- Modify: `.github/workflows/ci.yml:59-89` (the `selftest` job)

- [ ] **Step 1: Update the selftest job in `.github/workflows/ci.yml`**

Replace lines 59-89 (the entire `selftest` job) with:

```yaml
  selftest:
    name: Selftests (${{ matrix.os }} / ${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v6

      - uses: astral-sh/setup-uv@v8.1.0
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --python ${{ matrix.python-version }} --all-extras

      - name: Verify import
        run: uv run python -c "import vip; print(vip.__version__)"

      - name: Run selftests
        run: uv run pytest selftests/ -v --junitxml=selftest-results.xml --cov=src/vip --cov-report=term-missing

      - name: Collect VIP tests (dry run)
        run: uv run pytest src/vip_tests/ --collect-only --quiet

      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: selftest-results-${{ matrix.os }}-py${{ matrix.python-version }}
          path: selftest-results.xml
```

The artifact name now includes `${{ matrix.os }}` so the four matrix combos don't collide on upload.

- [ ] **Step 2: Validate the YAML locally**

Run: `uv run python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text()); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run selftests on macos-latest in addition to ubuntu-latest"
```

---

## Task 14: Create `mac-smoke.yml`

**Files:**
- Create: `.github/workflows/mac-smoke.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/mac-smoke.yml` with:

```yaml
name: Mac Smoke

on:
  push:
    branches: [main]
    paths:
      - 'docker/playwright-smoke.py'
      - 'pyproject.toml'
      - 'uv.lock'
      - 'src/**'
      - '.github/workflows/mac-smoke.yml'
  pull_request:
    paths:
      - 'docker/playwright-smoke.py'
      - 'pyproject.toml'
      - 'uv.lock'
      - 'src/**'
      - '.github/workflows/mac-smoke.yml'

jobs:
  smoke:
    name: macos-latest
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v6

      - uses: astral-sh/setup-uv@v8.1.0
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --frozen

      - name: vip install (Playwright Chromium)
        run: uv run vip install

      - name: Run smoke
        run: uv run python docker/playwright-smoke.py
```

- [ ] **Step 2: Validate the YAML locally**

Run: `uv run python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/mac-smoke.yml').read_text()); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/mac-smoke.yml
git commit -m "ci: add native macOS Playwright smoke workflow"
```

---

## Task 15: Final verification of full CI surface

**Files:** None (verification only)

- [ ] **Step 1: Lint, format, typecheck**

Run: `just check`
Expected: All checks pass.

Run: `just typecheck`
Expected: Success.

- [ ] **Step 2: Full selftest pass**

Run: `uv run pytest selftests/ -v`
Expected: All tests pass.

- [ ] **Step 3: Local RHEL smoke (regression check)**

Run: `just rhel9-smoke`
Expected: PASS line and clean uninstall, same as before. (Optional: `just rhel10-smoke`.)

- [ ] **Step 4: Local openSUSE Leap smoke**

Run: `just opensuse-leap-smoke`
Expected: PASS line and clean uninstall.

- [ ] **Step 5: Confirm git state is clean**

Run: `git status`
Expected: nothing to commit, working tree clean.

---

## Task 16: Delete the spec file

The spec served its purpose during implementation. The user has asked that we remove the spec at the end of the work (rather than re-adding `docs/superpowers/` to `.gitignore`).

**Files:**
- Delete: `docs/superpowers/specs/2026-05-08-mac-opensuse-ci-design.md`

- [ ] **Step 1: Remove the spec file**

Run: `git rm docs/superpowers/specs/2026-05-08-mac-opensuse-ci-design.md`
Expected: file removed; `git status` shows it as deleted.

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove mac/opensuse CI design spec after implementation"
```

---

## Notes for the implementer

- **TDD discipline:** Each task that touches Python code uses the test-first cycle (write failing test → implement → confirm pass). Don't skip the "verify it fails" step — it confirms the test actually exercises the new behavior.
- **`uv` everywhere:** Never invoke bare `python`, `pip`, or `playwright`. The codebase rule is `uv run` for everything.
- **Don't bypass `vip install`:** The openSUSE Dockerfile uses `uv run vip install`, not raw `playwright install --with-deps chromium`. This is enforced by `CLAUDE.md`.
- **CI cost note:** macOS runners bill at 10× standard runners. The `mac-smoke.yml` path filter scopes to runs that actually touch source/install code. The selftest matrix runs on every PR (acceptable given the small selftest runtime).
- **If openSUSE `python312` is unavailable:** Try `python311`. The `pyproject.toml` requires `>=3.10`, so 3.11 satisfies. Update the Dockerfile and note the substitution in the commit message — do not silently fall back.
