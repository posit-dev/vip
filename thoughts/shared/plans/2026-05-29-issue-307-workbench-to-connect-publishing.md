# Plan for issue #307: Publish to Connect from a Workbench session

## Context

VIP's existing `test_content_deploy.feature` validates Connect's publishing pipeline by deploying bundles via the Connect API, but it skips the user-facing workflow most customers exercise during UAT: opening a Workbench session and publishing from within it using tools like `rsconnect-python` or the Posit Publisher extension. A customer's UAT plan specifically requested two scenarios: (1) deploying a Python Shiny app from a VS Code/Positron terminal via `rsconnect-python`, and (2) deploying via the Posit Publisher extension UI. Both prove the chain Workbench → user-facing tool → Connect, which the current API-driven tests don't cover. Additionally, Python Shiny deployment is not currently tested at all (R Shiny is present, Python Shiny is not).

**Dependency status (as of merge of #349 / commit 3b336eb):**
- Terminal execution primitive: **available** — `terminal_run(page, cmd, ...)` in
  `src/vip_tests/workbench/exec.py` runs a shell command inside the IDE terminal via
  redirect-to-tempfile + DOM-rendered readback. The terminal scenario can be fully
  implemented.
- IDE extension installation primitive: **not yet implemented** — the merged code
  (`test_ide_extensions.py`) can only *verify* that extensions are already present, not
  install them. The Posit Publisher extension scenario remains blocked until that capability
  is added and must be gated with `pytest.skip`.

## Architecture

The feature file and step definitions live in `src/vip_tests/workbench/`, tagged with both
`@workbench` and `@connect`. The plugin's `_should_deselect_for_product` logic deselects
any item that carries a product marker whose product is not configured — so the test is
silently excluded from the run if either Workbench or Connect is absent. Placing the file
in `workbench/` (rather than `cross_product/`) keeps it in the `workbench` xdist group and
avoids a third `@cross_product` marker that would not add any deselection semantics for a
two-product test.

The test reuses the existing `"the user is logged in to Workbench"` step defined in
`src/vip_tests/workbench/test_sessions.py` (line 54). That step is registered with
`pytest-bdd`'s module-level `@given` decorator and is therefore visible to any step file
in the same `workbench/` package without redefinition. No new shared step registration
is needed.

### Fixtures supplying Connect credentials

The following session-scoped fixtures from `src/vip_tests/conftest.py` supply the Connect
credentials and URL needed by the deploy step:

- `connect_client` — `ConnectClient` instance (already authenticated); `None` when Connect
  is not configured
- `connect_url` — bare Connect URL string (`vip_config.connect.url`)
- `vip_config` — full config object; the raw Connect API key is at
  `vip_config.connect.api_key`, which is populated from `VIP_CONNECT_API_KEY` when not set
  in `vip.toml`

The `rsconnect deploy` CLI command receives the API key as a CLI argument:
```
rsconnect deploy shiny {bundle_path} --server {connect_url} --api-key {vip_config.connect.api_key} --title vip_test_shiny
```
This keeps the secret out of environment variables set at the subprocess level and
matches the pattern used in performance tests (`test_load.py`, `test_user_simulation.py`).

### Content cleanup — tracking fixtures promoted to root conftest

**Problem:** The three cleanup fixtures in `src/vip_tests/connect/conftest.py` —
`_connect_created_guids`, `_connect_content_cleanup`, and `_connect_end_of_run_sweep` —
are not visible from `src/vip_tests/workbench/`. A workbench test that creates Connect
content cannot register into that list.

**Decision: promote the fixtures to `src/vip_tests/conftest.py` (root).**

This is the correct option because:
1. The fixtures already guard against `connect_client is None` (lines 57–61 and 68–70 of
   `connect/conftest.py`), so they are safe to activate in workbench-only runs where
   Connect is not configured.
2. Moving them to the root is the DRY choice — no duplication of the cleanup pattern
   across packages, and any future cross-product test that creates Connect content
   automatically benefits.
3. The alternative (a duplicate minimal-cleanup fixture in the workbench conftest) would
   mean two separate tracking lists that never reconcile, leaving the end-of-run sweep
   incomplete from each package's perspective.

**Migration:** Remove the three fixtures from `src/vip_tests/connect/conftest.py` and add
them to `src/vip_tests/conftest.py`. Existing connect tests that already reference
`_connect_created_guids` by name (e.g. `test_packages.py`, `test_content_deploy.py`)
continue to resolve it from the root conftest without any change; pytest conftest
resolution walks up to the nearest ancestor that defines the fixture.

### Content GUID discovery — API lookup as primary, stdout parse as fallback

The deployed content GUID must be registered into `_connect_created_guids` so the
promoted cleanup fixtures delete it on pass or fail.

**Primary method: Connect API lookup by title.**

After `terminal_run` returns, query Connect for content with the title
`"vip_test_shiny_<worker_suffix>"` (the same title passed to `rsconnect deploy --title`).
The client already has `_find_content_by_name(name)` (a private method in
`src/vip/clients/connect.py`) that calls `GET /v1/content?name=<name>` and returns the
first match. The deploy step calls:

```python
content = connect_client._find_content_by_name(title)
assert content, f"Could not find deployed content '{title}' on Connect"
guid = content["guid"]
_connect_created_guids.append(guid)
```

This is robust to rsconnect CLI version changes and naturally dovetails with cleanup:
the title includes the `_vip_test` marker string (the tag sweep in `cleanup_vip_content`
uses the Connect tag API, not the name field, but the GUID-based cleanup path is the
primary route here).

**Fallback: stdout parse.**

If the API lookup returns `None` — which can happen when there is a race between
rsconnect finishing and Connect finishing the deploy asynchronously — attempt to extract
the GUID from the rsconnect CLI output line:

```
Output created: https://<host>/connect/#/apps/<guid>
```

using `re.search(r"/apps/([0-9a-f-]{36})", output)`. If neither path produces a GUID,
the cleanup step logs a warning and the end-of-run `cleanup_vip_content()` tag sweep
serves as the safety net.

**Why API lookup first:** The API is stable across rsconnect-python versions; the stdout
format has changed between releases (the line prefix and URL structure differ in older
versions). The `_find_content_by_name` path is already exercised by `create_content`'s
conflict-resolution logic, so it is tested implicitly.

## Components

**New files:**
- `src/vip_tests/workbench/test_publish_to_connect.feature` — Gherkin scenarios for
  terminal-based and UI-based publishing from Workbench to Connect (tags: `@workbench
  @connect`)
- `src/vip_tests/workbench/test_publish_to_connect.py` — Step definitions; imports
  `terminal_run` from `vip_tests.workbench.exec`
- `src/vip_tests/_bundles/python_shiny/app.py` — Minimal Python Shiny test app
- `src/vip_tests/_bundles/python_shiny/requirements.txt` — Dependencies for the Python
  Shiny bundle

**Modified files:**
- `src/vip_tests/conftest.py` — Add the three promoted cleanup fixtures:
  `_connect_created_guids`, `_connect_content_cleanup`, `_connect_end_of_run_sweep`
- `src/vip_tests/connect/conftest.py` — Remove those same three fixtures (now inherited
  from root)
- `src/vip_tests/workbench/conftest.py` — Add `python_shiny_bundle_path` fixture
  returning `Path(__file__).parent.parent / "_bundles" / "python_shiny"`, used to keep
  deploy step lean

**Not a deliverable at plan time:**
- `validation_docs/demo-bot-plan-issue-307.md` — A showboat demo requires running code to
  prove. This artifact must be created during or after implementation (run `just demo-save
  publish-to-connect`), not as part of the plan PR.

## Scenarios

### Scenario 1 (implementable now): terminal deploy via rsconnect-python

```gherkin
@workbench @connect
Scenario: User deploys a Python Shiny app from a Workbench terminal
  Given the user is logged in to Workbench
  And the user opens a VS Code session
  When the user deploys the Python Shiny app via the terminal
  Then the app is reachable on Connect
```

The `"the user is logged in to Workbench"` step is reused verbatim from
`test_sessions.py`. The deploy step calls:

```python
from vip_tests.workbench.exec import terminal_run

title = f"vip_test_shiny_{unique_session_name(__file__)}"

output = terminal_run(
    page,
    f"rsconnect deploy shiny {bundle_path} "
    f"--server {connect_url} --api-key {vip_config.connect.api_key} --title {title}",
    timeout=120_000,
    readback_lang="python",  # VS Code session without R extension
)

# Primary: API lookup by title (stable across rsconnect versions)
content = connect_client._find_content_by_name(title)
if content:
    guid = content["guid"]
else:
    # Fallback: parse stdout
    m = re.search(r"/apps/([0-9a-f-]{36})", output)
    guid = m.group(1) if m else None

if guid:
    _connect_created_guids.append(guid)
else:
    warnings.warn(f"Could not determine GUID for deployed content '{title}'; "
                  "relying on end-of-run tag sweep for cleanup.")
```

Cleanup happens automatically via the promoted `_connect_content_cleanup` fixture (runs
after every test, on pass or fail) and the session-scoped `_connect_end_of_run_sweep`
safety net. No explicit cleanup step in the Gherkin is needed — and none should be added,
because explicit cleanup steps fail silently when an earlier step raises, leaving content
behind.

### Scenario 2 (blocked — explicit skip): Posit Publisher extension UI

```python
@scenario("test_publish_to_connect.feature", "User deploys via Posit Publisher extension")
def test_publish_via_publisher():
    pytest.skip(
        reason=(
            "Posit Publisher extension UI scenario requires an IDE extension installation "
            "primitive that does not yet exist. Tracked as a follow-up capability gap."
        )
    )
```

The skip is placed on the test function itself (not inside a step) so pytest reports it
as `SKIPPED` with an actionable message rather than failing with a missing step error.
When the installation primitive lands, remove the `pytest.skip` and implement the steps.

## Verification

```bash
# Dry-run collection to verify the feature is recognized
uv run vip verify --config vip.toml --categories workbench --collect-only | grep "test_publish_to_connect"

# Run against a live Workbench + Connect deployment
uv run vip verify --config vip.toml --categories workbench -- -k publish_to_connect -v
```

Success criteria:
- Both scenarios are collected when `@workbench` and `@connect` products are configured
- Terminal scenario creates a Workbench session, runs `rsconnect deploy` via
  `terminal_run()`, discovers the GUID via Connect API title lookup (with stdout-parse
  fallback), appends it to `_connect_created_guids`, and verifies the app is reachable
  on Connect
- Publisher scenario is collected but immediately skipped with an actionable message
- Cleanup is automatic via the promoted `_connect_content_cleanup` autouse fixture —
  no explicit cleanup step in the Gherkin scenarios
- Neither scenario is collected when only one product is configured (plugin deselects both)
- Lint passes: `uv run ruff check src/vip_tests/ selftests/`

## Out of scope

- Implementing the IDE extension installation primitive — tracked separately as a
  misc-gaps issue. The Publisher scenario is stubbed with `pytest.skip` until it lands.
- Adding R Shiny publishing from Workbench — the issue specifically requests Python Shiny,
  and R Shiny deployment via Connect API is already covered in `test_content_deploy.feature`.
- Testing deployment failure scenarios (e.g., invalid credentials, missing permissions) —
  this plan focuses on the happy path to establish the baseline cross-product flow.
