# fix: show full skip/xfail reasons inline under -v

*2026-06-24T22:38:40Z by Showboat 0.6.1*
<!-- showboat-id: 558d9aa2-a861-4655-bbf0-da35d6756985 -->

Problem: with the default 'vip verify ... -- -v' run, pytest ellipsizes each SKIPPED reason to the terminal width, so the actionable part of the message is cut off (e.g. 'SKIPPED (Workbench session n...)').

Fix: src/vip/plugin.py bumps pytest's fine-grained *test-case* verbosity to 2 when (and only when) the user passed -v. At test-case verbosity >= 2 pytest prints the skip/xfail reason untrimmed (it may wrap, but no text is dropped). The global verbosity is left alone, so failure tracebacks and assertion reprs are unaffected — and skip reasons never carry a traceback. Dot mode (no -v) is untouched, and an explicit verbosity_test_cases in the user's config is respected.

```bash
uv run pytest selftests/test_plugin.py -k skip_reason -q -p no:cacheprovider 2>&1 | grep -E "passed|failed|error" | sed "s/ in [0-9.]*s//"
```

```output
2 passed
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
