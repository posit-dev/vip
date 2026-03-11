# Test inventory page for the VIP website

*2026-03-11T17:08:19Z by Showboat 0.6.1*
<!-- showboat-id: 99a3e3e4-8293-4b1e-a580-39102a2db165 -->

Added a new Test Inventory page to the VIP website (website/src/pages/test-inventory.astro) that:
- Parses all .feature files in the tests/ directory at build time
- Groups scenarios by product/category (Prerequisites, Connect, Workbench, Package Manager, Cross-product, Performance, Security)
- Displays feature names, descriptions, and full scenario/step details for each group
- Shows a sticky table of contents with scenario counts per group
- Includes a 'Where to start' callout to guide first-time users
- Added 'Test Inventory' link to the site navigation header

```bash
npm install --prefix website --silent && npm run build --prefix website 2>&1 | grep -c 'page(s) built'
```

```output
1
```

```bash
grep -o '[0-9]* feature files · [0-9]* scenarios' website/dist/test-inventory/index.html
```

```output
24 feature files · 54 scenarios
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E '^[0-9]+ passed' | sed 's/ in [0-9.]*s//' 
```

```output
52 passed, 1 warning
```

```bash
grep -o 'scenario-name' website/dist/test-inventory/index.html | wc -l | tr -d ' '
```

```output
56
```
