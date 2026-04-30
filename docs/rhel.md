# Installing vip on RHEL / Rocky / Alma / Oracle / CentOS

vip's local mode runs on RHEL-family Linux distributions via Playwright's
"fallback linux" mechanism. Chromium (headless and headed) is community-supported
on these distros; Firefox and WebKit are not.

This path is **not officially supported by Playwright** — the upstream maintainers
declined first-class RHEL support in [microsoft/playwright#40312] and pointed
users at the fallback. vip validates the path against RHEL 9 and RHEL 10 (UBI 9
and UBI 10) on every PR via the [`rhel-smoke` GitHub Actions workflow][workflow].

## What works

- ✅ Chromium, headless and headed
- ❌ Firefox (no fallback download)
- ❌ WebKit (no fallback download)
- ❌ `playwright install --with-deps` (apt-only; use `dnf` manually instead)

## Install

Install via vip's setup command:

```bash
uv sync
uv run vip install
```

`vip install` detects RHEL family, computes which Chromium runtime libraries
are missing, and (if you're not root) prints the exact `sudo dnf install`
command to run. After running it, re-run `uv run vip install` — it will
claim those packages in `.vip-install.json` and continue with `playwright
install chromium`.

The canonical package list lives in `src/vip/install/platform.py`
(`RHEL_PACKAGES`). The same list works on RHEL 9 and RHEL 10; Rocky / Alma /
Oracle / CentOS ship the same names.

To uninstall everything VIP installed: `uv run vip uninstall --yes --system`.
The `--system` flag prints the `sudo dnf remove` command for the packages it
recorded; user-space cleanup happens automatically.

## What you'll see

`uv run playwright install chromium` prints:

```
BEWARE: your OS is not officially supported by Playwright;
downloading fallback build for ubuntu24.04-x64.
```

This is expected. Playwright detects an unrecognized distro and downloads the
Ubuntu 24.04 Chromium build, which links against the libraries you installed
in step 1.

## RHEL 9 vs RHEL 10

Both are CI-tested. RHEL 10 ships glibc 2.39 (matching Ubuntu 24.04, the build
target of the fallback Chromium). RHEL 9 ships glibc 2.34, but Chromium's build
sysroot targets older glibc, so it works in practice. If you have the choice
and aren't constrained, RHEL 10 has the lower compatibility risk.

## Troubleshooting

**`error while loading shared libraries: libsomething.so.N`**
Find the package providing it:

```bash
sudo dnf provides "*/libsomething.so.N"
sudo dnf install -y <package>
```

Then retry `uv run playwright install chromium`. If you find a missing package
that should be in the default list above, please open an issue.

**Blank screenshots / glyph rendering issues**
Install fonts:

```bash
sudo dnf install -y liberation-fonts dejavu-sans-fonts google-noto-sans-fonts
```

[microsoft/playwright#40312]: https://github.com/microsoft/playwright/pull/40312
[workflow]: ../.github/workflows/rhel-smoke.yml
