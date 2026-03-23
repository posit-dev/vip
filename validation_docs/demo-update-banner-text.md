# Update website banner to say Posit Team

*2026-03-23T13:24:14Z by Showboat 0.6.1*
<!-- showboat-id: a1689f6e-42b7-46ff-9cd2-0fb6369a6063 -->

Updated the website hero banner heading from 'Verified Installation of Posit' to 'Verified Installation of Posit Team' in website/src/pages/index.astro.

```bash
grep -n 'Posit Team' website/src/pages/index.astro
```

```output
46:      <h1>Verified Installation<br />of Posit Team</h1>
48:        An extensible BDD test suite that validates your Posit Team deployment is installed correctly
```

```bash
just check
```

```output
bash: line 1: just: command not found
```

```bash
uv run ruff check src/ tests/ selftests/ examples/ && uv run ruff format --check src/ tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
89 files already formatted
All checks passed
```
