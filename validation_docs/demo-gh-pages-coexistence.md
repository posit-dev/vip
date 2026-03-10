# Feature: gh-pages coexistence for previews

*2026-03-10T20:53:00Z by Showboat 0.6.1*
<!-- showboat-id: d82f43ab-bd37-4c25-a24a-b8b0a3273035 -->

Updated GitHub workflows so main website publishing keeps the site at gh-pages root while PR previews are isolated under pr-preview/ and preserved during root deploys.

```bash
cd /home/runner/work/vip/vip && uv run python - <<'PY'
from pathlib import Path
import yaml
for rel in ['.github/workflows/preview.yml', '.github/workflows/website.yml']:
    yaml.safe_load(Path(rel).read_text(encoding='utf-8'))
    print(f'Parsed {rel}')
PY
```

```output
Parsed .github/workflows/preview.yml
Parsed .github/workflows/website.yml
```

```bash
cd /home/runner/work/vip/vip && uv run pytest selftests/ -q
```

```output
....................................................                     [100%]
=============================== warnings summary ===============================
src/vip/reporting.py:10
  /home/runner/work/vip/vip/src/vip/reporting.py:10: PytestCollectionWarning: cannot collect test class 'TestResult' because it has a __init__ constructor (from: selftests/test_reporting.py)
    @dataclass

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
52 passed, 1 warning in 0.37s
```

```bash
cd /home/runner/work/vip/vip && uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/
```

```output
All checks passed!
74 files already formatted
```
