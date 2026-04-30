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

### 1. Install Chromium's runtime libraries via dnf

```bash
sudo dnf install -y \
    nss nspr atk at-spi2-atk at-spi2-core cups-libs dbus-libs libdrm \
    mesa-libgbm glib2 pango cairo libX11 libxcb libXcomposite libXdamage \
    libXext libXfixes libxkbcommon libXrandr libXtst libxshmfence alsa-lib
```

The same package set works on RHEL 9 and RHEL 10. Rocky / Alma / Oracle / CentOS
ship the same names.

### 2. Install vip via uv

```bash
just setup-rhel
```

Or manually:

```bash
uv sync
uv run playwright install chromium
```

Note: do **not** pass `--with-deps` to `playwright install` on RHEL —
it hardcodes `apt-get` and will fail.

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
