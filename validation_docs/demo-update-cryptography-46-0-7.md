# chore: bump cryptography to 46.0.7 for CVE-2026-39892

*2026-04-10T12:41:16Z by Showboat 0.6.1*
<!-- showboat-id: dd4fa59b-5d6e-41b9-9a82-daf72685df17 -->

Updated the cryptography dependency floor from 46.0.6 to 46.0.7 to address CVE-2026-39892, and refreshed uv.lock.

```bash
grep cryptography pyproject.toml
```

```output
    "cryptography>=46.0.7",  # CVE-2026-39892 fix; transitive via boto3/urllib3
```

```bash
grep 'name = "cryptography"' uv.lock -A1 | head -4
```

```output
    { name = "cryptography" },
    { name = "msal" },
--
name = "cryptography"
```

```bash
uv run pytest selftests/ -q --tb=no 2>&1 | grep -oE '[0-9]+ passed'
```

```output
110 passed
```

```bash
uv run --with ruff ruff check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1 && uv run --with ruff ruff format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1
```

```output
All checks passed!
96 files already formatted
```
