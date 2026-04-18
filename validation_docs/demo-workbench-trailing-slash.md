# fix(config): normalize product URLs to include trailing slash

*2026-04-18T01:34:47Z by Showboat 0.6.1*
<!-- showboat-id: 9ea36791-fdba-404f-be64-3ca991537ad5 -->

Updated _normalize_url() in src/vip/config.py to ensure all product URLs end with a trailing slash. Without the slash, nginx redirects e.g. https://host/pwb to http://host/pwb/ (note: HTTP not HTTPS), which Playwright cannot follow in a headless HTTPS context. Since BaseClient already strips trailing slashes via rstrip('/'), API calls are unaffected.

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
