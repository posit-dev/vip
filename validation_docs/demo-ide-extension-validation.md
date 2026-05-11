# feat: validate IDE extension installation

*2026-05-11T14:24:00Z by Showboat 0.6.1*
<!-- showboat-id: 80980009-bd9b-42f7-a8e5-b3aa3a0cc31d -->

This PR validates that required IDE extensions are installed in every Workbench session VIP launches. The Posit Workbench integration extension is always checked (closing the parity gap with platform-integration-tests). Admins can declare additional required extensions per IDE in vip.toml under [workbench.extensions]; those are verified via the Extensions panel (VS Code / Positron) or the Extension Manager (JupyterLab).

## What changed

- New BDD feature with three scenarios — one per IDE — that reuse the session lifecycle from `test_ide_launch`.
- New `WorkbenchExtensionsConfig` dataclass for the optional `[workbench.extensions]` block.
- Page-object selectors added to `vscode_session`, `positron_session`, and `jupyterlab_session`.
- Extension IDs are validated against a public regex (`EXTENSION_ID_RE`) before being interpolated into CSS selectors, preventing selector injection from a malicious vip.toml.
- `_as_str_list` rejects lists containing non-string elements (per Copilot review).

## Config selftests pass

The new `WorkbenchExtensionsConfig` is covered by 7 selftests, including the strict list-content validation added in response to review.

```bash
uv run pytest selftests/test_config.py -k WorkbenchExtensionsConfig --no-header -q 2>&1 | grep -E '^[0-9]+ passed|FAILED|ERROR' | sed 's/ in [0-9.]*s//'
```

```output
7 passed
```

## Bad config raises a clear error

A vip.toml that puts a non-string into `workbench.extensions.vscode` is rejected at load time with a useful error message:

```bash
uv run python -c "
from vip.config import WorkbenchExtensionsConfig
try:
    WorkbenchExtensionsConfig.from_dict({'vscode': ['quarto.quarto', 42]})
except ValueError as e:
    print(f'ValueError: {e}')
"
```

```output
ValueError: workbench.extensions.vscode must be a list of strings, got list containing int
```

## Extension-ID selector guard

`EXTENSION_ID_RE` is now a public symbol shared by `VSCodeSession` and `PositronSession`. It restricts extension IDs to a safe character set before they are interpolated into a CSS selector. Anything else raises immediately:

```bash
uv run python -c "
from vip_tests.workbench.pages.vscode_session import VSCodeSession, EXTENSION_ID_RE
from vip_tests.workbench.pages.positron_session import PositronSession
assert EXTENSION_ID_RE.match('quarto.quarto'), 'safe ID rejected'
print(f'safe selector: {VSCodeSession.extension_list_item(\"quarto.quarto\")}')
print(f'safe selector: {PositronSession.extension_list_item(\"quarto.quarto\")}')
try:
    VSCodeSession.extension_list_item(\"'); evil--\")
except ValueError as e:
    print(f'rejected: {e}')
"
```

```output
safe selector: .extension-list-item[data-extension-id='quarto.quarto']
safe selector: .extension-list-item[data-extension-id='quarto.quarto']
rejected: Invalid extension ID (contains unsafe characters): "'); evil--"
```

## BDD scenarios are collected

The three new scenarios are visible to pytest:

```bash
uv run pytest --collect-only -q src/vip_tests/workbench/test_ide_extensions.py 2>&1 | grep '::' | sed 's|.*test_ide_extensions|test_ide_extensions|'
```

```output
test_ide_extensions.py::test_vscode_extensions[chromium]
test_ide_extensions.py::test_jupyterlab_extensions[chromium]
test_ide_extensions.py::test_positron_extensions[chromium]
```

## Lint and format clean

`just check` runs ruff in lint and format-check mode across all source trees.

```bash
just check 2>&1 | tail -5
```

```output
uv run ruff check src/ selftests/ examples/ docker/
All checks passed!
uv run ruff format --check src/ selftests/ examples/ docker/
126 files already formatted
```
