# fix: trigger PyPI publish on tag push, not release event

*2026-03-23T14:41:48Z by Showboat 0.6.1*
<!-- showboat-id: 90df04f3-e1df-4042-8f07-2b305a4b42e2 -->

The publish.yml workflow was triggered on 'release: types: [published]'. However, GitHub suppresses workflow triggers when the GITHUB_TOKEN is used to create the release — so the PyPI publish workflow never fired (zero runs ever). The fix is to trigger on 'push: tags: v*' exactly like docker.yml does.

```bash
cat .github/workflows/publish.yml
```

```output
name: Publish to PyPI

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    name: Build distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6

      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Build wheel and sdist
        run: uv build

      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    name: Publish to PyPI
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/vip
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - uses: pypa/gh-action-pypi-publish@release/v1
```

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/ && echo 'Lint OK'
```

```output
All checks passed!
89 files already formatted
Lint OK
```

```bash
uv run pytest selftests/ -q --tb=short 2>&1 | grep -oE '^[0-9]+ passed'
```

```output
95 passed
```
