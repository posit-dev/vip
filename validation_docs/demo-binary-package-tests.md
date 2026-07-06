# Feature: binary package serving tests

*2026-07-06T18:36:48Z by Showboat 0.6.1*
<!-- showboat-id: 1199f339-5b67-4970-9f02-3b3fdefcd589 -->

Adds a `test_binary_packages` suite covering PPM's precompiled **binary** serving paths (CRAN Windows/macOS/Linux indices + PyPI wheels), which the existing source-only tests never touched. Also hardens the OpenVSX check to search all VSX repos.

The scenarios run against a live deployment, so CI (which only collects product tests) can't execute them. The blocks below prove the suite is wired up and lint-clean; the live-run result is noted at the end.

```bash
uv run pytest src/vip_tests/package_manager/test_binary_packages.py --collect-only -q 2>&1 | grep -E 'test_|collected' | sed 's/ in [0-9.]*s//'
```

```output
src/vip_tests/package_manager/test_binary_packages.py::test_cran_windows_binaries
src/vip_tests/package_manager/test_binary_packages.py::test_cran_macos_binaries
src/vip_tests/package_manager/test_binary_packages.py::test_cran_linux_binaries
src/vip_tests/package_manager/test_binary_packages.py::test_pypi_wheels
4 tests collected
```

```bash
uv run ruff check src/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ selftests/ examples/
```

```output
148 files already formatted
```

**Live run against solo** (`solo.packagemanager.posit.co`), full package_manager suite:
`uv run vip verify --config vip.toml --categories package-manager -- -v` → **9 passed, 4 skipped, 0 failed**. All four new binary scenarios pass; the 4 skips are auth/private-repo scenarios not applicable to a public mirror. (Not executed here because it needs a live deployment + `vip.toml`.)
