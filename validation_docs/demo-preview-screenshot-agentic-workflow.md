# Feature: preview screenshot agentic workflow

*2026-04-06T19:56:51Z by Showboat 0.6.1*
<!-- showboat-id: 5bd446a1-d0be-41b5-a55d-d115db2148b2 -->

Added a GitHub Agentic Workflow that runs after Website Preview completes, captures full-page screenshots for report and website preview pages, uploads them as PR assets, and posts a summary comment.

```bash
gh aw compile preview-screenshot-gallery
```

```output
✓ .github/workflows/preview-screenshot-gallery.md (63.3 KB)
✓ Compiled 1 workflow(s): 0 error(s), 0 warning(s)
```

```bash
gh aw validate preview-screenshot-gallery
```

```output
✓ .github/workflows/preview-screenshot-gallery.md
✓ Compiled 1 workflow(s): 0 error(s), 0 warning(s)
```

```bash
UV_NO_PROGRESS=1 uv run --extra dev ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
UV_NO_PROGRESS=1 uv run --extra dev ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
96 files already formatted
```

```bash
uv run pytest selftests/ -q --disable-warnings | sed -E 's/in [0-9]+\.[0-9]+s/in <time>s/'
```

```output
/home/runner/work/vip/vip/src/vip/plugin.py:106: UserWarning: Config file not found: vip.toml
  vip_cfg = load_config(config.getoption("--vip-config"))
........................................................................ [ 65%]
......................................                                   [100%]
110 passed, 2 warnings in <time>s
```
