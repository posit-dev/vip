# Feature: anonymous (none) git auth mode

*2026-06-24T15:33:09Z by Showboat 0.6.1*
<!-- showboat-id: d06f42a9-f1b6-4539-af0a-5ae9f71e7e76 -->

Adds auth_method='none' to [workbench.git_test]: clone scenarios run against a public repo with no VIP_GIT_TOKEN; push/commit scenarios skip.

```bash
uv run pytest selftests/test_config.py::TestGitTestConfig -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
15 passed
```

```bash
uv run pytest src/vip_tests/workbench/test_git_ops.py --collect-only -q 2>&1 | grep -E 'tests? collected' | sed 's/ in [0-9.]*s//'
```

```output
no tests collected (6 deselected)
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
159 files already formatted
```
