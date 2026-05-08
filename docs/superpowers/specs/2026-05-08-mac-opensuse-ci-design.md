# macOS and openSUSE CI coverage

## Goal

Extend VIP's CI to validate the codebase on macOS and openSUSE Leap, in
addition to the current Ubuntu and RHEL coverage. Both platforms get
selftests and the headless Chromium smoke test that already runs for
RHEL 9 and RHEL 10.

This requires teaching `src/vip/install/` about `suse-family` (zypper)
hosts. macOS is already a supported `vip install` target; only CI work
is needed there.

Out of scope:
- Windows support (deferred).
- openSUSE Tumbleweed (Leap only for now).
- Additional macOS architectures (macos-latest / arm64 only).

## Background

Today's CI (relevant pieces):

- `.github/workflows/ci.yml` runs lint, typecheck, dependency audit, and
  selftests on `ubuntu-latest` (Python 3.10 and 3.12).
- `.github/workflows/rhel-smoke.yml` builds Docker images for `rhel9`
  and `rhel10`, runs `vip install` inside the container, then runs
  `docker/rhel-smoke.py` to launch headless Chromium against a data
  URL and assert the page renders.
- `src/vip/install/platform.py` detects `rhel-family`, `debian-family`,
  `macos`, or `unsupported`, and ships pinned package lists for the
  first two. macOS does not need system packages; Playwright bundles
  Chromium's runtime on macOS.
- `src/vip/install/runner.py` knows two managers: `dnf` and `apt`.

## Architecture

The change touches three layers:

1. **Install module** (`src/vip/install/`) — add `suse-family` and
   `zypper` as a third manager.
2. **Smoke script** (`docker/`) — generalize the platform-agnostic
   Chromium smoke into a single `playwright-smoke.py` reused by all
   Linux Dockerfiles and by the new macOS smoke job.
3. **CI workflows** (`.github/workflows/`) — extend selftest matrix to
   include macOS, rename `rhel-smoke.yml` to `linux-smoke.yml` with an
   `opensuse-leap` matrix entry, and add a new `mac-smoke.yml`.

## Component changes

### `src/vip/install/platform.py`

Add SUSE family detection:

```python
_SUSE_LIKE = {"opensuse-leap", "opensuse-tumbleweed", "sles", "suse"}
```

In `detect()`, after the existing rhel-like / debian-like branches,
match SUSE candidates and return `family="suse-family"`. SUSE distros
set `ID=opensuse-leap` (or similar) and `ID_LIKE="suse opensuse"`, so
either ID or ID_LIKE membership in `_SUSE_LIKE` qualifies.

Add a pinned package list:

```python
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
```

The list is the SUSE-named equivalent of `RHEL_PACKAGES`, derived by
mapping each Chromium runtime lib through `zypper search --provides`
on `opensuse/leap:15`. Add a `LIST_REVIEWED_AGAINST_PLAYWRIGHT_SUSE`
constant alongside the existing one so the parity check covers SUSE.

### `src/vip/install/plan.py`

Add a `suse-family` branch in plan construction so that the resulting
`InstallPlan.system_step` carries `manager="zypper"` and
`packages=SUSE_PACKAGES` (filtered to those not already installed).
Pre-installed detection on SUSE uses `rpm -q` because zypper is a
front-end over RPM — no new code in `packages.py` is required, but a
selftest should pin this assumption.

### `src/vip/install/runner.py`

Three small changes, all keyed on `manager == "zypper"`:

- `_manager_for("suse-family")` returns `"zypper"`.
- `_install_system_packages` adds a zypper branch:
  `subprocess.run(["zypper", "install", "-y", "--no-confirm", *packages], check=True)`.
  (`--no-confirm` is redundant with `-y` on modern zypper but keeps the
  command robust across older Leap releases.)
- `format_install_plan` prints `sudo zypper install -y …` instead of
  the dnf/apt strings when `system_step.manager == "zypper"`.

### `src/vip/install/manifest.py`

`SystemPackageItem.manager` is already a free-form string; serialized
manifests just record `"zypper"`. No schema or migration work needed.
A round-trip selftest pins the expectation.

### `docker/playwright-smoke.py` (renamed from `docker/rhel-smoke.py`)

Replace `_rhel_major_version()` with `_platform_label()` that returns:

- On Linux, the `ID` plus major `VERSION_ID` from `/etc/os-release`
  (e.g. `rhel9`, `leap15`, `opensuse-leap15`).
- On macOS, `f"macos-{platform.mac_ver()[0]}"`.

Update the success line to `PASS: {label} headless chromium smoke`.
The Chromium interaction itself is unchanged.

### Linux Dockerfiles

`docker/rhel9/Dockerfile`, `docker/rhel10/Dockerfile`, and the new
`docker/opensuse-leap/Dockerfile` all invoke
`uv run python /app/docker/playwright-smoke.py` instead of the
RHEL-named script.

### `docker/opensuse-leap/Dockerfile` (new)

```dockerfile
# openSUSE Leap headless Chromium smoke test image
FROM opensuse/leap:15

RUN zypper -n install \
        python312 python312-pip procps gzip tar \
    && zypper clean --all

COPY --from=ghcr.io/astral-sh/uv:0.6.3 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY . .

RUN uv sync --frozen

# Runs as root, so vip install invokes zypper directly.
RUN uv run vip install

CMD ["uv", "run", "python", "/app/docker/playwright-smoke.py"]
```

`opensuse/leap:15` ships Python 3.6 by default; the `python312`
package provides 3.12 to satisfy `pyproject.toml`.

### `.github/workflows/ci.yml`

Extend the `selftest` job's matrix to include macOS:

```yaml
selftest:
  name: Selftests (${{ matrix.os }} / ${{ matrix.python-version }})
  runs-on: ${{ matrix.os }}
  strategy:
    fail-fast: false
    matrix:
      os: [ubuntu-latest, macos-latest]
      python-version: ["3.10", "3.12"]
```

Four selftest jobs total. `lint`, `typecheck`, and `audit` stay on
`ubuntu-latest` only — no value in duplicating those.

### `.github/workflows/linux-smoke.yml` (renamed from rhel-smoke.yml)

Rename the workflow file, update the workflow `name:` to `Linux Smoke`,
and extend the matrix:

```yaml
matrix:
  version: [rhel9, rhel10, opensuse-leap]
```

The existing `docker/${{ matrix.version }}/Dockerfile` path resolution
already picks up the new `docker/opensuse-leap/Dockerfile`. Path
filters expand to include `docker/opensuse-leap/**`.

### `.github/workflows/mac-smoke.yml` (new)

Native macOS smoke job, no Docker:

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
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v6
      - uses: astral-sh/setup-uv@v8.1.0
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run vip install
      - run: uv run python docker/playwright-smoke.py
```

## Tests

New selftests under `selftests/install/`:

- **`test_platform.py`** — parametrized cases for `opensuse-leap`,
  `opensuse-tumbleweed`, and `sles` `/etc/os-release` payloads
  resolving to `family="suse-family"`. Confirm a Tumbleweed payload
  with `ID_LIKE="suse"` also resolves correctly.
- **`test_plan.py`** — a `suse-family` `PlatformInfo` produces an
  `InstallPlan` whose `system_step.manager == "zypper"` and packages
  match `SUSE_PACKAGES` (or the pending-filtered subset).
- **`test_runner.py`** — mock `subprocess.run`; assert
  `_install_system_packages("zypper", pkgs)` invokes
  `["zypper", "install", "-y", "--no-confirm", *pkgs]`. Assert that
  `format_install_plan` prints `sudo zypper install -y …` for the
  non-root suse case.
- **`test_manifest.py`** — write and re-read a manifest containing a
  `SystemPackageItem(manager="zypper", …)`.

All four selftests run on macOS without invoking real zypper, so they
also validate the new macOS CI runner path.

## Consequences and trade-offs

- **Cost**: macOS GitHub-hosted runners bill at 10× standard runners.
  Two macOS selftest jobs and one macOS smoke job run per push/PR
  matching the path filters. Path filters on `mac-smoke.yml` keep this
  scoped; the selftest matrix runs on every PR (acceptable given the
  small selftest runtime).
- **Reverse coverage**: openSUSE Tumbleweed remains untested. If
  Tumbleweed-specific drift appears (e.g. package renames), it surfaces
  via customer reports rather than CI. Mitigated by the parametrized
  detection selftest covering Tumbleweed `os-release` payloads.
- **Smoke script rename**: `docker/rhel-smoke.py` → `playwright-smoke.py`
  is a one-shot churn but eliminates per-platform duplication.
- **No `vip install` changes for macOS**: the existing macOS branch
  (Playwright-only, no system packages) is exactly what the new
  `mac-smoke.yml` job exercises end-to-end.

## Open questions

None blocking implementation.
