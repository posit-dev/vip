# Feature: preview screenshot agentic workflow

*2026-04-06T18:54:30Z by Showboat 0.6.1*
<!-- showboat-id: b5c2d9a4-b3ed-435e-af0c-6be3a4ffc0da -->

Added a GitHub Agentic Workflow that runs after Website Preview completes, captures full-page screenshots for report and website preview pages, uploads them as PR assets, and posts a summary comment.

```bash
gh aw compile preview-screenshot-gallery
```

```output
✓ .github/workflows/preview-screenshot-gallery.md (61.6 KB)
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
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
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
