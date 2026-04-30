# Feature: vip install and vip uninstall

*2026-04-30T21:43:55Z by Showboat 0.6.1*
<!-- showboat-id: 6c156e8d-5edd-4b5b-a3a0-8cd39ba8f318 -->

## Selftests for the new install package

```bash
uv run pytest selftests/install/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
83 passed, 1 warning
```

## Lint and format

```bash
uv run ruff check src/vip/install/ selftests/install/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/vip/install/ selftests/install/
```

```output
17 files already formatted
```

## CLI: vip install --help

```bash
uv run vip install --help
```

```output
usage: vip install [-h] [--skip-system] [--dry-run]

Install VIP's machine-side dependencies: Chromium runtime libraries (via dnf or apt) and Playwright's Chromium browser. Records what was installed in .vip-install.json so vip uninstall can reverse only what this command added.

options:
  -h, --help     show this help message and exit
  --skip-system  Skip the system-package step (e.g., if you don't have sudo).
  --dry-run      Print the plan without executing.
```

## CLI: vip uninstall --help

```bash
uv run vip uninstall --help
```

```output
usage: vip uninstall [-h] [--yes] [--venv] [--system] [--force-host]
                     [--connect-url CONNECT_URL] [--api-key API_KEY]

Reverse vip install using the per-project .vip-install.json manifest. Default scope removes the Playwright cache and the manifest. Pass --venv to also remove .venv/ and --system to print the sudo command for removing system packages. Always prints a dry-run plan; pass --yes to execute.

options:
  -h, --help            show this help message and exit
  --yes
  --venv
  --system
  --force-host
  --connect-url CONNECT_URL
                        Connect URL for chained vip cleanup (default: config /
                        autodetect).
  --api-key API_KEY
```

## Dry-run install on this dev host (macOS — system step is a no-op; Playwright is already cached)

```bash
uv run vip install --dry-run
```

```output
vip install: already up to date.
```

## End-to-end overall selftest count (no regressions)

```bash
uv run pytest selftests/ -q --ignore=selftests/test_load_engine.py 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
411 passed, 20 warnings
```
