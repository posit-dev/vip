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

### Content GUID flow (cleanup via `target_fixture`)

The deployed content's GUID must flow from the deploy step to the cleanup step without
using a module-level global. Use a `pytest.fixture`-backed dict as `target_fixture`:

```python
@pytest.fixture
def publish_context():
    """Holds the Connect content GUID created during publishing."""
    return {"guid": None}

@when("the user deploys the Python Shiny app via the terminal", target_fixture="publish_context")
def deploy_via_terminal(page, publish_context, ...):
    output = terminal_run(page, "rsconnect deploy shiny ...")
    # parse GUID from rsconnect output
    publish_context["guid"] = _parse_guid(output)
    return publish_context

@then("the published content is cleaned up")
def cleanup_published_content(connect_client, publish_context):
    guid = publish_context.get("guid")
    if guid:
        connect_client.delete_content(guid)
```

`connect_client.delete_content(guid)` calls `DELETE /__api__/v1/content/{guid}` and is
already implemented in `src/vip/clients/connect.py`. If the deploy step did not produce
a GUID (e.g., because it was skipped), the cleanup step is a no-op.

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
- `src/vip_tests/workbench/conftest.py` — Add `publish_context` fixture if it should be
  session-scoped across future publishing tests; otherwise define it locally in the step
  file. The Python Shiny bundle path should be a module-level constant or a `@pytest.fixture`
  returning `Path(__file__).parent.parent / "_bundles" / "python_shiny"` to keep steps
  lean.

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
  And the published content is cleaned up
```

The `"the user is logged in to Workbench"` step is reused verbatim from
`test_sessions.py`. The deploy step calls:

```python
from vip_tests.workbench.exec import terminal_run

output = terminal_run(
    page,
    f"rsconnect deploy shiny {bundle_path} "
    f"--server {connect_url} --api-key {connect_api_key} --title vip_test_shiny",
    timeout=120_000,
    readback_lang="python",  # VS Code session without R extension
)
```

The GUID is parsed from the rsconnect CLI output line
`"Output created: https://<host>/connect/#/apps/<guid>"` using a regex.

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
  `terminal_run()`, parses the GUID, and verifies the app is reachable on Connect
- Publisher scenario is collected but immediately skipped with an actionable message
- Cleanup step deletes the deployed content item via `connect_client.delete_content(guid)`;
  GUID flows through `publish_context` fixture dict, never a module-level global
- Neither scenario is collected when only one product is configured (plugin deselects both)
- Lint passes: `uv run ruff check src/vip_tests/ selftests/`

## Out of scope

- Implementing the IDE extension installation primitive — tracked separately as a
  misc-gaps issue. The Publisher scenario is stubbed with `pytest.skip` until it lands.
- Adding R Shiny publishing from Workbench — the issue specifically requests Python Shiny,
  and R Shiny deployment via Connect API is already covered in `test_content_deploy.feature`.
- Testing deployment failure scenarios (e.g., invalid credentials, missing permissions) —
  this plan focuses on the happy path to establish the baseline cross-product flow.
