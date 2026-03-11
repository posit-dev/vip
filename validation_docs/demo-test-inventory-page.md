# Test inventory page for the VIP website

*2026-03-11T13:53:54Z by Showboat 0.6.1*
<!-- showboat-id: 04ddf5c2-4630-49ac-b58d-a462e14483ad -->

Added a new Test Inventory page to the VIP website (website/src/pages/test-inventory.astro) that:
- Parses all .feature files in the tests/ directory at build time
- Groups scenarios by product/category (Prerequisites, Connect, Workbench, Package Manager, Cross-product, Performance, Security)
- Displays feature names, descriptions, and full scenario/step details for each group
- Shows a sticky table of contents with scenario counts per group
- Includes a 'Where to start' callout to guide first-time users
- Added 'Test Inventory' link to the site navigation header

```bash
cd website && npm run build 2>&1 | grep -E '(page.s. built|Complete)'  | sed 's/[0-9][0-9]:[0-9][0-9]:[0-9][0-9]/TIME/' | sed 's/in [0-9]*ms/in Xs/g'
```

```output
TIME [build] ✓ Completed in Xs.
TIME [build] ✓ Completed in Xs.
TIME ✓ Completed in Xs.
TIME [build] 3 page(s) built in Xs
TIME [build] Complete!
```

```bash
grep -o '[0-9]* feature files · [0-9]* scenarios' website/dist/test-inventory/index.html
```

```output
24 feature files · 54 scenarios
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error'
```

```output
52 passed, 1 warning in 0.30s
```

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/ && echo 'All lint and format checks passed'
```

```output
All checks passed!
74 files already formatted
All lint and format checks passed
```
