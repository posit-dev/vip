# Feature: interactive-auth poll-loop tests + headless-only CI stance (#430)

*2026-07-08T18:06:17Z by Showboat 0.6.1*
<!-- showboat-id: d5836841-c7bf-4e8d-a299-1fe7558dbf09 -->

Issue #430 asked whether to automate `--interactive-auth` E2E against the mock IdP, or document a headless-only stance. Decision: headless-only. `start_interactive_auth` blocks on a *human* clicking through the IdP, so CI automation would need a second CDP-driving process plus Xvfb for coverage that is mostly test scaffolding. Instead we pin the interactive-only poll-loop logic with unit tests (the real gap) and record the decision. This demo shows the new tests passing and lint/format/type checks green.

```bash
env -u UV_PROJECT -u VIRTUAL_ENV uv run pytest selftests/test_auth.py::TestStartInteractiveAuthPollLoop -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
3 passed
```

```bash
env -u UV_PROJECT -u VIRTUAL_ENV uv run pytest selftests/test_auth.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
80 passed
```

```bash
env -u UV_PROJECT -u VIRTUAL_ENV uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
env -u UV_PROJECT -u VIRTUAL_ENV uv run ruff format --check selftests/test_auth.py
```

```output
1 file already formatted
```

```bash
env -u UV_PROJECT -u VIRTUAL_ENV uv run mypy src/vip/ 2>&1 | tail -1
```

```output
Success: no issues found in 28 source files
```

The stance is also recorded where a maintainer will see it: the .github/workflows/mock-idp-e2e.yml comment now reads as a settled headless-only decision (not deferred work), pointing at the decision record in thoughts/shared/plans/2026-07-08-issue-430-interactive-auth-headless-only.md.
