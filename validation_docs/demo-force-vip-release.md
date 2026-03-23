# chore(release): bump version to 0.9.3 to test PyPI release process

*2026-03-23T13:34:55Z by Showboat 0.6.1*
<!-- showboat-id: abb2565a-7757-471b-8558-cc4691b7b305 -->

Bumped version from 0.9.2 to 0.9.3 in pyproject.toml to trigger a new PyPI release and test the release pipeline end-to-end.

```bash
grep '^version' pyproject.toml
```

```output
version = "0.9.3"
version_toml = ["pyproject.toml:project.version"]
version_variables = ["src/vip/__init__.py:__version__"]
```

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
89 files already formatted
All checks passed
```
