# Plan for issue #301: Add in-session execution primitives for Workbench

## Context

VIP currently validates that Workbench sessions launch successfully and can display basic UI elements, but it never executes meaningful code inside those sessions beyond a single `1 + 1` example in the RStudio console. This gap blocks approximately 15 customer-facing acceptance scenarios that a UAT-running customer has identified, including package installation verification, document rendering, database connectivity, and runtime version detection from within active sessions.

The existing `rstudio_executes_r_code` step in `src/vip_tests/workbench/test_ide_launch.py` demonstrates the shape (focus console, type expression, press Enter, wait for output), but it only asserts that a substring (`[1] 2`) appears somewhere in the console pane — it never *captures and returns* the output of a specific expression. The acceptance criterion in #301 requires exactly that (`result = rstudio_eval(page, "packageVersion('Matrix')"); assert "1." in result`), so the real work is a capture mechanism, not a copy of the existing step.

Issue #301 names four execution surfaces as the deliverable: (1) R in the RStudio console, (2) Python in Positron / JupyterLab / VS Code, (3) a shell command in an IDE terminal whose output is read back, and (4) rendering a document and verifying the artifact lands on disk. All four are in scope for this primitive; none are deferred. The plan commits to a single capture technique — **marker-bracketed output** — that serves all of them, plus a redirect-to-file readback path for terminals that sidesteps the one genuinely hard problem (scraping xterm's canvas-rendered widget).

The outcome is a foundation layer that test authors can build on to express scenarios like "install the sf package from PPM and verify GDAL is reachable" or "render a Quarto document and confirm the HTML output exists" without duplicating console-interaction logic in every test.

## Architecture

This change adds a new module `src/vip_tests/workbench/exec.py` that houses execution primitives. All of them share one capture technique so the same logic is exercised everywhere:

**Marker-bracketed capture.** Each helper wraps the caller's expression so the output is fenced by a unique sentinel — e.g. for R, `cat("<<VIP-START-{uuid}>>\n"); <expr>; cat("<<VIP-END-{uuid}>>\n")`; the Python/Jupyter equivalents use `print()`. The helper types the wrapped statement, waits for the end sentinel to appear in the DOM-rendered console/cell output, then returns the text *between* the markers. This solves the three hard parts the existing step ignores — distinguishing this command's output from prior scrollback, discarding the echoed input, and knowing when execution is done — and it works identically across RStudio, Positron, and JupyterLab because all three render console/cell output to the DOM.

**Terminals without scraping the widget.** VS Code/Positron integrated terminals render through xterm.js to a canvas/WebGL surface, so reading the widget's text directly is unreliable. `terminal_run` therefore does *not* read the terminal: it types `<cmd> > <tmpfile> 2>&1; echo <<VIP-DONE-{uuid}>>`, waits for the done sentinel, and reads the captured output back from `<tmpfile>` through a DOM-rendered surface (a language console, or `read_file` below). This makes terminal execution a committed capability rather than a spike, and keeps the only fragile dependency (canvas text scraping) entirely out of the design.

**Filesystem readback.** `file_exists` / `read_file` run a tiny console expression (`file.exists(...)` / `readLines(...)` in R, `os.path.exists` / `open().read()` in Python) and capture the result via the same marker mechanism. These satisfy acceptance criterion #4 (render a document, verify the artifact lands on disk) and back the `terminal_run` readback path.

The primitives delegate to existing page object selectors in `src/vip_tests/workbench/pages/` (e.g., `ConsolePaneSelectors`, `PositronSession`, `JupyterLabSession`) for locator construction, ensuring that selector maintenance remains centralized and execution logic is decoupled from DOM details.

Step definitions for new scenarios (package installation, document rendering, database queries, etc.) will live in separate test files under `src/vip_tests/workbench/` and call into `exec.py` as needed. The BDD layer remains thin; complexity lives in the reusable helpers.

## Components

All primitives share the marker-bracketed capture helper described in Architecture and return the captured text (or raise on timeout / missing end marker).

**New files:**
- `src/vip_tests/workbench/exec.py` — execution primitives module

  **Console/cell eval (DOM-rendered output → real capture):**
  - `rstudio_eval(page: Page, expr: str, timeout: int = 30000) -> str` — evaluate R in the RStudio console
  - `positron_eval_r(page: Page, expr: str, timeout: int = 30000) -> str` — evaluate R in the Positron console
  - `positron_eval_python(page: Page, expr: str, timeout: int = 30000) -> str` — evaluate Python in the Positron console
  - `jupyterlab_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30000) -> str` — evaluate code in a JupyterLab cell (Python or R kernel)
  - `vscode_eval(page: Page, expr: str, lang: str = "python", timeout: int = 30000) -> str` — evaluate code in VS Code via the Python/R extension REPL (DOM-rendered output panel), not the integrated terminal

  **Terminal execution (redirect + readback, no widget scraping):**
  - `terminal_run(page: Page, cmd: str, timeout: int = 30000) -> str` — run a shell command in any IDE terminal by redirecting stdout/stderr to a temp file and emitting a done sentinel, then returning the file contents via `read_file`. Covers the uv-venv, `code-server --install-extension`, and shell-driven install scenarios.

  **Filesystem readback (satisfies "verify artifact lands on disk"):**
  - `file_exists(page: Page, path: str, timeout: int = 30000) -> bool` — check a path exists via a console expression
  - `read_file(page: Page, path: str, timeout: int = 30000) -> str` — read a file's contents via a console expression

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

The terminal + readback path should be exercised end-to-end against a live Workbench, since it is the one part with no existing precedent:

```bash
# terminal_run writes to a temp file; file_exists / read_file read it back
uv run pytest src/vip_tests/workbench/test_exec_live.py -v --vip-config vip.toml
```

Additionally, a new selftest package should be added under `selftests/workbench/` (new directory) to validate the pure logic extracted from the helpers:

```bash
uv run pytest selftests/workbench/test_exec.py -v
```

The selftests do not require a live Workbench deployment. They should focus on the deterministic pure functions — marker wrapping (the `<<VIP-START/END>>` fencing of an arbitrary expression), output extraction between markers, optional normalization (e.g. stripping R's `[1]` prefix), and timeout/missing-marker error branching — not on re-asserting selector strings.

## Open questions

- **Output parsing strategy**: The current `rstudio_executes_r_code` step uses `expect(console_output).to_contain_text("[1] 2")` to assert on console output. Should the primitives return raw console text and leave parsing/assertion to the caller, or should they offer optional post-processing (e.g., strip R's `[1]` prefix)? **UNCONFIRMED** — the initial implementation will return raw text by default and may expose parser helpers that are unit-tested in `selftests/workbench/test_exec.py`.

- **Multi-line expression handling**: Some scenarios (e.g., `renv::restore()`) may require multiple lines or waiting for intermediate prompts (package installation progress). Should the primitives handle this, or should callers break multi-step interactions into separate `eval` calls? **UNCONFIRMED** — the initial implementation assumes single-line expressions; multi-line scenarios can chain calls or use semicolons.

- **IDE readiness**: The current `rstudio_executes_r_code` waits for console input visibility with a generous timeout (`TIMEOUT_IDE_LOAD`). Should the primitives inherit this pattern, or should callers handle readiness separately (e.g., in a `given` step)? **UNCONFIRMED** — the initial implementation will wait for console readiness as part of each `eval` call, accepting the redundancy in exchange for self-contained primitives.

- **Terminal readback channel per IDE**: `terminal_run` redirects to a temp file and reads it back through a DOM-rendered surface — in RStudio/Positron/JupyterLab that surface is the language console/cell. Pure VS Code (no Positron extension) has no R/Python console by default, so its `read_file` must go through the Python extension REPL. **Decision**: implement `read_file` on top of `vscode_eval` for VS Code so there is always a DOM-rendered readback channel; we never scrape the xterm widget. To validate during implementation: confirm the done sentinel reliably flushes to the file before `read_file` runs (add a short retry on the sentinel, not a fixed sleep).

- **API shape as IDEs grow**: Should we retain explicit `*_eval` helpers, or introduce an IDE-keyed dispatch map that routes to shared internals? **UNCONFIRMED** — keep explicit helpers initially for clarity, then reassess once additional IDE-specific evaluators are added.

## Out of scope

- **Debugging helpers** — primitives for setting breakpoints, stepping through code, or inspecting variables during execution. The primitives are purely for expression evaluation and output capture, not interactive debugging.

- **Async execution** — running code in the background and polling for completion. All primitives block until the expression completes or times out. Long-running operations (e.g., `renv::restore()`) must fit within the caller-specified timeout.

- **Multi-session orchestration** — launching multiple IDE sessions in parallel and coordinating execution across them. Each primitive operates on a single `Page` object representing a single active session.

- **Scraping the xterm terminal widget** — reading text directly off the canvas/WebGL-rendered terminal is explicitly not done. Terminal output is captured by redirecting to a temp file and reading it back through a DOM-rendered surface (`terminal_run` + `read_file`); this is the design, not a fallback.

- **Performance benchmarking** — measuring expression execution time or resource usage. The primitives focus on correctness (did the expression succeed?) rather than performance (how fast was it?).
