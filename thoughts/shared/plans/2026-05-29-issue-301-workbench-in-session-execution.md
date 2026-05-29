# Plan for issue #301: Add in-session execution primitives for Workbench

## Context

VIP currently validates that Workbench sessions launch successfully and can display basic UI elements, but it never executes meaningful code inside those sessions beyond a single `1 + 1` example in the RStudio console. This gap blocks approximately 15 customer-facing acceptance scenarios that a UAT-running customer has identified, including package installation verification, document rendering, database connectivity, and runtime version detection from within active sessions.

The existing `rstudio_executes_r_code` step in `src/vip_tests/workbench/test_ide_launch.py` demonstrates the pattern (focus console, type expression, press Enter, wait for output), but it's tightly coupled to a single test and not reusable. This proposal extracts and generalizes that pattern into a set of execution primitives that work across all four Workbench IDEs (RStudio, Positron, JupyterLab, VS Code) and support R, Python, and shell execution contexts.

The outcome is a foundation layer that test authors can build on to express scenarios like "install the sf package from PPM and verify GDAL is reachable" or "render a Quarto document and confirm the HTML output exists" without duplicating console-interaction logic in every test.

## Architecture

This change adds a new module `src/vip_tests/workbench/exec.py` that houses the execution primitives. Each primitive is a standalone function that takes a Playwright `Page` object and an expression string, handles the mechanics of console focus / typing / output capture / timeout, and returns the captured output as a string or raises on failure.

The primitives delegate to existing page object selectors in `src/vip_tests/workbench/pages/` (e.g., `ConsolePaneSelectors`, `PositronSession`, `JupyterLabSession`) for locator construction, ensuring that selector maintenance remains centralized and execution logic is decoupled from DOM details.

Step definitions for new scenarios (package installation, document rendering, database queries, etc.) will live in separate test files under `src/vip_tests/workbench/` and call into `exec.py` as needed. The BDD layer remains thin; complexity lives in the reusable helpers.

## Components

**New files:**
- `src/vip_tests/workbench/exec.py` — execution primitives module
  - `rstudio_eval(page: Page, expr: str, timeout: int = 30000) -> str` — evaluate R code in RStudio console
  - `positron_eval_r(page: Page, expr: str, timeout: int = 30000) -> str` — evaluate R code in Positron console
  - `positron_eval_python(page: Page, expr: str, timeout: int = 30000) -> str` — evaluate Python code in Positron console
  - `jupyterlab_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30000) -> str` — evaluate code in JupyterLab cell (Python or R kernel)
  - `vscode_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30000) -> str` — evaluate code in VS Code integrated terminal (Python REPL or R)
  - `ide_terminal_run(page: Page, cmd: str, timeout: int = 30000) -> str` — run a shell command in any IDE's terminal and capture output

**Modified files:**
- `src/vip_tests/workbench/test_ide_launch.py` — refactor `rstudio_executes_r_code` to call `rstudio_eval` from `exec.py`, preserving the existing test behavior but delegating to the shared primitive
- `src/vip/config.py` — add optional `test_packages: list[str]` field to `WorkbenchConfig` for deployment-agnostic package-install scenarios (e.g., `["sf", "DBI", "Matrix"]`)

**Future files (out of scope for this plan; enabled by it):**
- `src/vip_tests/workbench/test_package_install.feature` + `.py` — scenarios for installing R/Python packages from PPM, GitHub, PyPI
- `src/vip_tests/workbench/test_document_rendering.feature` + `.py` — scenarios for knitting RMarkdown and rendering Quarto documents
- `src/vip_tests/workbench/test_database_connectivity.feature` + `.py` — scenarios for DBI / odbc / SQLAlchemy / psycopg queries

## Verification

A reviewer can confirm the change works by running the refactored RStudio test:

```bash
uv run pytest src/vip_tests/workbench/test_ide_launch.py::test_rstudio_launches_and_executes_r -v --vip-config vip.toml
```

The test should pass identically to its current behavior, but the console output should show the step delegating to `exec.rstudio_eval`.

Additionally, a new selftest should be added to validate the error-handling path (timeout when an expression hangs, exception when output doesn't match expected format):

```bash
uv run pytest selftests/workbench/test_exec.py -v
```

The selftests do not require a live Workbench deployment; they use Playwright's mock page objects or stub the Playwright API to verify that the primitives construct the correct locators and handle timeout exceptions properly.

## Open questions

- **Output parsing strategy**: The current `rstudio_executes_r_code` step uses `expect(console_output).to_contain_text("[1] 2")` to assert on console output. Should the primitives return raw console text and leave parsing/assertion to the caller, or should they offer optional post-processing (e.g., strip R's `[1]` prefix)? **UNCONFIRMED** — the initial implementation will return raw text and push parsing responsibility to step definitions, maintaining flexibility.

- **Multi-line expression handling**: Some scenarios (e.g., `renv::restore()`) may require multiple lines or waiting for intermediate prompts (package installation progress). Should the primitives handle this, or should callers break multi-step interactions into separate `eval` calls? **UNCONFIRMED** — the initial implementation assumes single-line expressions; multi-line scenarios can chain calls or use semicolons.

- **IDE readiness**: The current `rstudio_executes_r_code` waits for console input visibility with a generous timeout (`TIMEOUT_IDE_LOAD`). Should the primitives inherit this pattern, or should callers handle readiness separately (e.g., in a `given` step)? **UNCONFIRMED** — the initial implementation will wait for console readiness as part of each `eval` call, accepting the redundancy in exchange for self-contained primitives.

## Out of scope

- **Debugging helpers** — primitives for setting breakpoints, stepping through code, or inspecting variables during execution. The primitives are purely for expression evaluation and output capture, not interactive debugging.

- **Async execution** — running code in the background and polling for completion. All primitives block until the expression completes or times out. Long-running operations (e.g., `renv::restore()`) must fit within the caller-specified timeout.

- **Multi-session orchestration** — launching multiple IDE sessions in parallel and coordinating execution across them. Each primitive operates on a single `Page` object representing a single active session.

- **Output artifact verification** — checking that a rendered document or installed package appears in the file system or package library. The primitives return console output only; file-system assertions are the caller's responsibility.

- **Performance benchmarking** — measuring expression execution time or resource usage. The primitives focus on correctness (did the expression succeed?) rather than performance (how fast was it?).
