# fix(example-report): skip Package Manager when RSPM_LICENSE is unavailable

*2026-03-26T00:16:17Z by Showboat 0.6.1*
<!-- showboat-id: a6885218-9f47-44b7-be78-3e3e39573e49 -->

The website-preview CI job calls example-report.yml to build a validation report. This job was failing with 'The trial has expired' when the RSPM_LICENSE secret was unavailable (e.g. Dependabot PRs or fork PRs). Package Manager falls back to trial mode when the license env var is empty, and the trial built into the ubuntu2204-2024.08.0 image has since expired.

The packagemanager-smoke.yml workflow already handles this correctly: it has a 'Check for RSPM_LICENSE' step that detects an empty secret and gracefully skips all PM steps. The example-report.yml lacked this check and failed hard.

The fix adds the same pattern to example-report.yml:
- A 'Check for RSPM_LICENSE' step that sets pm-license.available to true/false
- All PM-related steps are conditionalized with: if: steps.pm-license.outputs.available == 'true'
- A 'Check for license errors' step to surface actionable annotations when PM fails
- The vip.toml and deployment name dynamically include or omit PM depending on availability
- The Stop Package Manager cleanup step is also conditionalized to avoid errors

```bash
ruff check src/ tests/ selftests/ examples/ && ruff format --check src/ tests/ selftests/ examples/ && echo 'All checks passed'
```

```output
All checks passed!
89 files already formatted
All checks passed
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -oE '^[0-9]+ passed'
```

```output
95 passed
```

```bash
grep -n 'pm-license\|Check for RSPM\|Check for license errors' .github/workflows/example-report.yml
```

```output
16:      - name: Check for RSPM_LICENSE
17:        id: pm-license
52:        if: steps.pm-license.outputs.available == 'true'
64:        if: steps.pm-license.outputs.available == 'true'
79:      - name: Check for license errors
80:        if: failure() && steps.pm-license.outputs.available == 'true'
100:        if: steps.pm-license.outputs.available == 'true'
118:        if: steps.pm-license.outputs.available == 'true'
144:          if [ "${{ steps.pm-license.outputs.available }}" = "true" ]; then
153:          if [ "${{ steps.pm-license.outputs.available }}" = "true" ]; then
196:        if: always() && steps.pm-license.outputs.available == 'true'
```
