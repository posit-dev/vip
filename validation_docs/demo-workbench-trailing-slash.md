# fix(config): normalize product URLs to include trailing slash

*2026-04-18T00:37:03Z by Showboat 0.6.1*
<!-- showboat-id: 5223e341-b886-4efe-b5a2-5775183cddef -->

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
uv tool run ruff check src/ selftests/ examples/ && uv tool run ruff format --check src/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
99 files already formatted
All checks passed
```
