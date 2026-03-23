# feat: publish wheels to PyPI on releases

*2026-03-23T12:55:29Z by Showboat 0.6.1*
<!-- showboat-id: fe52402f-806a-4316-bd71-cb775dc2d072 -->

Added .github/workflows/publish.yml to build and publish wheels (and sdist) to PyPI whenever a GitHub release is published. The workflow uses PyPI Trusted Publishing (OIDC) so no PyPI API token secret is required — just a one-time setup of the publisher on pypi.org under the 'pypi' environment.

```bash
cat .github/workflows/publish.yml
```

```output
name: Publish to PyPI

on:
  release:
    types: [published]

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
uv build --no-sources 2>&1 | tail -5
```

```output
Building source distribution...
Building wheel from source distribution...
Successfully built dist/vip-0.9.2.tar.gz
Successfully built dist/vip-0.9.2-py3-none-any.whl
```

```bash
just check
```

```output
bash: line 1: just: command not found
```

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
89 files already formatted
All checks passed
```
