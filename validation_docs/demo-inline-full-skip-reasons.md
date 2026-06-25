# fix: show full skip/xfail reasons inline under -v

*2026-06-24T22:55:59Z by Showboat 0.6.1*
<!-- showboat-id: 47266cb6-4730-4624-8a68-d1fb6caf9323 -->

Problem: with the default 'vip verify ... -- -v' run, pytest ellipsizes each SKIPPED reason to the terminal width, so the actionable part of the message is cut off (e.g. 'SKIPPED (Workbench session n...)').

Fix: src/vip/plugin.py bumps pytest's fine-grained *test-case* verbosity to 2 when (and only when) the user passed -v. At test-case verbosity >= 2 pytest prints the skip/xfail reason untrimmed (it may wrap, but no text is dropped). The global verbosity is left alone, so failure tracebacks and assertion reprs are unaffected — and skip reasons never carry a traceback. Dot mode (no -v) is untouched, and an explicit verbosity_test_cases in the user's config is respected.

Tests: a treatment test asserts the full reason (and trailing sentinel) appears with no '...)' ellipsis; a control test defeats the bump via '-o verbosity_test_cases=1' and asserts the SAME reason IS ellipsized — proving COLUMNS=80 is honored in-process and that the bump (not a vacuous setup) is what removes the truncation.

```bash
uv run pytest selftests/test_plugin.py -k skip_reason -q -p no:cacheprovider 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
3 passed
```

```bash
printf "import pytest\n\n@pytest.mark.skip(reason=\"Workbench session not established by --interactive-auth (landed on login page: https://workbench.posit.example.com/auth-sign-in?appUri=)\")\ndef test_push_rstudio():\n    pass\n" > _demo_skip.py
printf "[general]\ndeployment_name = \"Demo\"\n" > _demo_vip.toml
COLUMNS=220 uv run pytest _demo_skip.py -v -p no:cacheprovider --vip-config=_demo_vip.toml 2>&1 | grep "push_rstudio"
rm -f _demo_skip.py _demo_vip.toml
```

```output
_demo_skip.py::test_push_rstudio SKIPPED (Workbench session not established by --interactive-auth (landed on login page: https://workbench.posit.example.com/auth-sign-in?appUri=))                                  [100%]
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/vip/plugin.py selftests/test_plugin.py
```

```output
All checks passed!
2 files already formatted
```

Second fix in this branch: when --interactive-auth (or --headless-auth) is passed but no auth-requiring product is configured (e.g. only Package Manager), the 'skipping browser authentication' warning was emitted once per xdist worker. pytest_configure runs on the controller AND every worker; only the controller had a session to forward, so workers fell through to the controller-only auth branch and re-warned. With auto-detected workers this floods the output (1 + N copies). The fix guards the worker branch so workers only restore forwarded credentials and never re-run the controller logic.

```bash
printf "[general]\ndeployment_name = \"Demo\"\n[package_manager]\nurl = \"https://p3m.dev/\"\n" > _demo_vip.toml
printf "def test_placeholder():\n    assert True\n" > _demo_pm.py
echo -n "warning count: "
uv run pytest _demo_pm.py --vip-config=_demo_vip.toml --interactive-auth -n 2 -W always -p no:cacheprovider 2>&1 | grep -c "skipping browser authentication"
rm -f _demo_vip.toml _demo_pm.py
```

```output
warning count: 1
```

```bash
uv run pytest selftests/test_plugin.py -k "no_auth_products_warning_not_duplicated or skip_reason" -q -p no:cacheprovider 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
4 passed
```
