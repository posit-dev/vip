# preview screenshot agentic workflow

*2026-04-06T21:08:15Z by Showboat 0.6.1*
<!-- showboat-id: f305a6b8-8d7d-4ade-888d-29ff2eb7ece5 -->

Added a GitHub Agentic Workflow that captures full-page Playwright screenshots of PR preview pages and posts them inline in a PR comment. The workflow was compiled and validated locally with `gh aw compile` and `gh aw validate` (both passed with 0 errors, 0 warnings).

```bash
ls .github/workflows/preview-screenshot-gallery.md .github/workflows/preview-screenshot-gallery.lock.yml
```

```output
.github/workflows/preview-screenshot-gallery.lock.yml
.github/workflows/preview-screenshot-gallery.md
```

```bash
grep -c "upload-asset\|add-comment\|upload_asset" .github/workflows/preview-screenshot-gallery.lock.yml
```

```output
14
```

```bash
grep "assets/" .github/workflows/preview-screenshot-gallery.lock.yml | head -1 | tr -d " \""
```

```output
GH_AW_ASSETS_BRANCH:assets/preview-screenshot-gallery
```

```bash
uv sync --extra dev > /dev/null 2>&1 && uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ > /dev/null && echo "All checks passed"
```

```output
All checks passed!
All checks passed
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -oE "^[0-9]+ passed"
```

```output
110 passed
```

The workflow instructs the agent to render screenshots inline using Markdown image syntax (`![alt](<url>)`) so images are directly visible in the PR comment body.
