# RHEL 9 and RHEL 10 headless Chromium smoke

*2026-04-30T00:22:50Z by Showboat 0.6.1*
<!-- showboat-id: 23649e9a-cc97-4fad-a330-c40dadafb5d1 -->

Validates that vip's headless Chromium path works on RHEL via Playwright's 'fallback linux' mechanism. Each Dockerfile installs the required shared libraries via dnf, then runs docker/rhel-smoke.py. The CI matrix in .github/workflows/rhel-smoke.yml runs the same on every PR. Closes posit-dev/vip#227.

```bash
just check
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
105 files already formatted
```

```bash
just rhel9-smoke 2>&1 | grep -oE '(BEWARE|PASS).*' | sort -u
```

```output
PASS: rhel9 headless chromium smoke
```

rhel10 cannot run locally on this Apple Silicon machine: Docker Desktop's qemu emulation of linux/amd64 hits a TLS provider mismatch when fetching from Red Hat's UBI 10 CDN ('digital envelope routines::provider signature failure'). The CI runner (ubuntu-latest, native amd64) has no such limitation — both rhel9 and rhel10 jobs run there as a matrix on every PR via .github/workflows/rhel-smoke.yml. The rhel10 Dockerfile is structurally identical to rhel9's (same dnf list, same uv install, same CMD), with FROM redhat/ubi10 in place of redhat/ubi9, so the only meaningful runtime difference is glibc 2.39 vs 2.34.
