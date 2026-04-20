# fix(config): normalize product URLs to include trailing slash

*2026-04-20T23:21:41Z by Showboat 0.6.1*
<!-- showboat-id: 71737c56-e322-4c57-9ac6-fddf3d63dba3 -->

Updated _normalize_url() in src/vip/config.py to ensure sub-path URLs end with a trailing slash. Without it, nginx redirects e.g. https://host/pwb to http://host/pwb/ (HTTP, not HTTPS), which Playwright cannot follow in a headless context. Host-only URLs (e.g. https://connect.example.com) are left without a trailing slash so f"{url}/__api__/..." callers are unaffected. urllib.parse is used for correct URL manipulation.

```bash
uv run pytest selftests/test_config.py -q 2>&1 | grep -E '^[0-9]+ (passed|failed)' | sed 's/ in [0-9.]*s//'
```

```output
44 passed, 1 warning
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E '^[0-9]+ (passed|failed)' | sed 's/ in [0-9.]*s//'
```

```output
246 passed, 4 warnings
```

```bash
uv tool run ruff@0.15.0 check src/ selftests/ examples/ 2>&1 | grep -v 'Downloading\|Downloaded\|Installed\|package in' && uv tool run ruff@0.15.0 format --check src/ selftests/ examples/ 2>&1 | grep -v 'Downloading\|Downloaded\|Installed\|package in' && echo 'All checks passed'
```

```output
All checks passed!
99 files already formatted
All checks passed
```
