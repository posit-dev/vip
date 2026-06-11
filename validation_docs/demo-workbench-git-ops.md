# feat: Git operations from Workbench sessions (closes #306)

*2026-06-11T16:15:51Z by Showboat 0.6.1*
<!-- showboat-id: d2fbfa7c-6018-4317-a28e-41a1fc0b877f -->

Implemented Git operations testing for Workbench sessions: terminal git clone/branch/commit/push across RStudio, VS Code, Positron IDEs, plus RStudio Git-pane GUI scenario. Added GitTestConfig block with VIP_GIT_TOKEN env fallback, two-layer branch cleanup, and 19 selftests.

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -5
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -5
```

```output
145 files already formatted
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
704 passed, 3 skipped, 20 warnings
```

```bash
uv run pytest src/vip_tests/workbench/test_git_ops.py --collect-only -q 2>&1 | grep -E 'deselected|collected' | head -5
```

```output
no tests collected (7 deselected) in 0.01s
```

```bash
uv run pytest selftests/test_config.py -k 'git' -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
19 passed
```
