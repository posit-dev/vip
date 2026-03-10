# Feature: gh-pages coexistence for previews

*2026-03-10T21:03:58Z by Showboat 0.6.1*
<!-- showboat-id: fd767ab0-6104-4e13-990a-cf4b0e9e1e0a -->

This demo is CI-stable: it bootstraps dependencies, validates both workflow files, runs selftests with normalized timing output, and runs lint/format checks.

```bash
cd /home/runner/work/vip/vip && uv sync --all-extras >/dev/null 2>&1 && echo 'uv sync complete'
```

```output
uv sync complete
```

```bash
cd /home/runner/work/vip/vip && uv run python - <<'PY'
from pathlib import Path
for rel in ['.github/workflows/preview.yml', '.github/workflows/website.yml']:
    text = Path(rel).read_text(encoding='utf-8')
    required = ('name:', 'on:', 'jobs:')
    missing = [key for key in required if key not in text]
    if missing:
        raise SystemExit(f'Missing {missing} in {rel}')
    print(f'Validated {rel}')
PY
```

```output
Validated .github/workflows/preview.yml
Validated .github/workflows/website.yml
```

```bash
cd /home/runner/work/vip/vip && set -o pipefail && uv run pytest selftests/ -q | sed -E 's/in [0-9.]+s/in <time>/g'
```

```output
....................................................                     [100%]
=============================== warnings summary ===============================
src/vip/reporting.py:10
  /home/runner/work/vip/vip/src/vip/reporting.py:10: PytestCollectionWarning: cannot collect test class 'TestResult' because it has a __init__ constructor (from: selftests/test_reporting.py)
    @dataclass

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
52 passed, 1 warning in <time>
```

```bash
cd /home/runner/work/vip/vip && uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/
```

```output
All checks passed!
74 files already formatted
```
