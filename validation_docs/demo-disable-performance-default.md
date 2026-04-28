# Feature: opt-in performance category

*2026-04-28T22:57:34Z by Showboat 0.6.1*
<!-- showboat-id: bfe8f978-a740-4060-9e97-4d1a3191a890 -->

Performance tests are now excluded from the default vip verify run. Enable with --performance-tests.

```bash
uv run pytest selftests/test_cli_verify.py::TestPerformanceOptIn -n 0 -v 2>&1 | grep -E 'PASSED|FAILED|passed|failed' | sed 's/ in [0-9.]*s//' | sort
```

```output
============================== 4 passed ===============================
selftests/test_cli_verify.py::TestPerformanceOptIn::test_categories_overrides_performance_tests_flag PASSED [ 75%]
selftests/test_cli_verify.py::TestPerformanceOptIn::test_default_filter_excludes_performance PASSED [ 25%]
selftests/test_cli_verify.py::TestPerformanceOptIn::test_opt_in_constant_includes_performance PASSED [100%]
selftests/test_cli_verify.py::TestPerformanceOptIn::test_performance_tests_flag_includes_performance PASSED [ 50%]
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
104 files already formatted
```

Verify the default marker expression now excludes performance, and that --performance-tests removes the exclusion.

```bash
uv run python -c "
from argparse import Namespace
from unittest.mock import patch, MagicMock
captured = []
def fake_run(cmd, **kw):
    captured.append(cmd)
    r = MagicMock(); r.returncode = 0; return r
with patch('vip.cli.subprocess.run', side_effect=fake_run), patch('vip.cli.sys.exit'):
    from vip.cli import _run_verify_local, DEFAULT_TEST_TIMEOUT_SECONDS
    base = dict(config=None, connect_url='https://c.example.com', workbench_url=None,
        package_manager_url=None, report='report/results.json', interactive_auth=False,
        no_auth=True, extensions=[], categories=None, filter_expr=None, pytest_args=[],
        verbose=False, test_timeout=DEFAULT_TEST_TIMEOUT_SECONDS, headless_auth=False, idp=None)
    _run_verify_local(Namespace(**base, performance_tests=False))
    _run_verify_local(Namespace(**base, performance_tests=True))
for label, cmd in zip(['default                  ', 'with --performance-tests'], captured):
    idx = [i for i, t in enumerate(cmd) if t == '-m']
    print(f'{label}: -m', repr(cmd[idx[1]+1]))
" 2>&1 | grep '^.*-m '
```

```output
default                  : -m 'not config_hygiene and not performance'
with --performance-tests: -m 'not config_hygiene'
```
