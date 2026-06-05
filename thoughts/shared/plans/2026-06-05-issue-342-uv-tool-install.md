# Plan for issue #342: Cleaner install with uv tool install

## Context

Today the documented install flow tells users to create a venv (`uv venv`),
activate it, then run `uv pip install posit-vip` and `uv run vip install`.
The author of #342 points out that `uv tool install posit-vip` collapses
that into one command, puts `vip` on the user's PATH directly (no
`uv run` prefix), and isolates the install in its own environment so it
does not interfere with whatever Python environment is active in the
current directory.

This is a documentation-and-ergonomics improvement, not a behavior
change. The package is already published to PyPI as `posit-vip` with a
`vip` console-script entry point in `pyproject.toml`, so
`uv tool install posit-vip` works today — but no docs mention it. We
also want to document `uv tool install git+https://github.com/posit-dev/vip`
for users who need to install straight from `main` without cloning.

The intended outcome is: every user-facing install instruction (README,
website quick start, Shiny app page) leads with `uv tool install`, and
the existing `uv sync` / `uv run` flow is retained only where it makes
sense (the RStudio/Positron clone-the-repo workflow and the dev recipes
in `justfile`).

## Architecture

The change is concentrated in user-facing documentation, plus one small
hardening change in `src/vip/install/playwright.py` so `vip install` can
find the Playwright CLI when `vip` itself is running from an isolated
uv-tool venv whose `bin/` directory is not on the user's `PATH`.

- Docs that mention installing the package:
  - `README.md`
  - `website/src/pages/index.astro`
  - `website/src/pages/getting-started.astro`
  - `website/src/pages/shiny-app.astro`
- Code-change scope:
  - `src/vip/install/playwright.py` — change the playwright subprocess
    invocation from `["playwright", "install", "chromium"]` to
    `[sys.executable, "-m", "playwright", "install", "chromium"]` so the
    lookup goes through the same Python interpreter that runs `vip`,
    regardless of whether the `playwright` script is on the user's
    `PATH`.
- Test scope:
  - `selftests/install/test_playwright.py` — update the existing
    `subprocess.Popen` argv assertion to the new invocation form, and
    add a regression check that `argv[:3] == [sys.executable, "-m",
    "playwright"]`.

The four-layer test architecture is unaffected — this is install-time
tooling, not BDD test code.

## Components

**Documentation (no behavior change):**

- `README.md` — replace the "Quick start" block (currently
  `uv venv` / `source .venv/bin/activate` / `uv pip install posit-vip`
  / `uv run vip install` / `vip verify ...`) with:

  ```bash
  uv tool install posit-vip
  vip install
  vip verify --connect-url https://connect.example.com --interactive-auth
  ```

  Add a short note immediately below: "To install straight from `main`,
  use `uv tool install git+https://github.com/posit-dev/vip` instead."
  Keep the rest of the README (uninstall, CLI commands, Shiny app,
  development) unchanged.

- `website/src/pages/index.astro` — line 92 in the "How it works"
  step 1: change `uv pip install posit-vip` to
  `uv tool install posit-vip` and drop the `uv run` prefix from the
  `vip install` line on the next row.

- `website/src/pages/getting-started.astro` — the `#quick-start`
  section (lines 33–42): replace the `uv pip install posit-vip` /
  `uv run vip install` block with `uv tool install posit-vip` /
  `vip install`. Keep the "Using RStudio or Positron?" sub-block
  unchanged because that flow intentionally wants a local checkout
  for editing tests, which `uv tool install` does not provide.

- `website/src/pages/shiny-app.astro` — the "Installing with pip"
  subsection (lines 240–244): keep `pip install posit-vip` as the
  explicit-pip option, and add a `pipx install posit-vip` alternative
  so the no-uv path also gets the cleaner isolated-tool flavor.

**Code (so `vip install` works from a uv-tool venv):**

- `src/vip/install/playwright.py` — in `install_chromium()`:
  - Change `subprocess.Popen(["playwright", "install", "chromium"], …)`
    to `subprocess.Popen([sys.executable, "-m", "playwright",
    "install", "chromium"], …)`.
  - Update the `OSError` branch's error message in
    `PlaywrightInstallError` to reference `python -m playwright` so
    diagnostics match the new invocation. No public API change.

**Tests:**

- `selftests/install/test_playwright.py`:
  - Update the existing test that asserts on the argv passed to
    `subprocess.Popen` (it currently expects
    `["playwright", "install", "chromium"]`).
  - Add a regression test
    `test_install_chromium_uses_module_invocation` that mocks
    `subprocess.Popen` and asserts
    `argv[:3] == [sys.executable, "-m", "playwright"]` so the
    uv-tool guarantee is encoded. The existing test that exercises the
    `OSError` path stays, with its expected error message updated to
    match.

## Verification

1. **Lint and selftests** (must pass on every PR):

   ```bash
   uv run ruff check src/ selftests/
   uv run pytest selftests/install/test_playwright.py -v
   ```

   Success: ruff is clean and the playwright selftests pass, including
   the new `python -m playwright` assertion.

2. **Smoke the new install path on a clean machine** (manual; not CI):

   ```bash
   uv tool install posit-vip
   vip --version
   vip install
   vip status --help
   uv tool uninstall posit-vip
   ```

   Success: `vip install` completes, drops a `.vip-install.json`
   manifest under `$HOME`, and a follow-up `vip uninstall` reverses
   exactly what `vip install` recorded.

3. **Smoke the from-source variant**:

   ```bash
   uv tool install git+https://github.com/posit-dev/vip
   vip --version
   uv tool uninstall posit-vip
   ```

   Success: pulls `main`, exposes `vip` on `PATH`, and the version
   string matches `pyproject.toml`.

4. **Render the Astro site locally** to confirm the docs read
   correctly:

   ```bash
   cd website && npm install && npm run build
   ```

   Success: build completes; the `index.astro`,
   `getting-started.astro`, and `shiny-app.astro` pages render with
   the new install commands.

## Open questions

- **UNCONFIRMED**: Whether `uv tool` prepends the tool's venv `bin/`
  to `PATH` for child processes spawned from the tool's entry point.
  If it does, the `playwright.py` change is belt-and-suspenders
  rather than strictly required. The change is still worth making
  because `python -m playwright` is the more portable invocation
  form (no PATH dependency) and gives a clearer error if Playwright
  is somehow missing from the same venv as `vip`.
- **UNCONFIRMED**: Whether to keep the "Using RStudio or Positron?"
  sub-block of `getting-started.astro` exactly as-is. Proposal: keep
  it — that flow exists because Workbench users want a local checkout
  they can edit, which `uv tool install` does not give them.
- Whether to also document `pipx install posit-vip` in the README
  quick start. Proposal: do not — the README leads with uv to match
  the rest of the project; the Shiny app page already has a
  "without uv" carve-out and is the right place for the pipx mention.

## Out of scope

- Changing the published package name on PyPI or the `vip` script
  entry point — `posit-vip` and the `vip` script in `pyproject.toml`
  are already correct.
- Updating the `Dockerfile` — the container image continues to use
  `uv sync --frozen` because it builds from a source checkout, not
  from PyPI.
- Updating `justfile` recipes — `just setup`, `just lint`, etc.
  target a checkout and intentionally use `uv sync` / `uv run`.
- Updating `CHANGELOG.md` — auto-generated by semantic-release; the
  PR title is enough.
- Adding a `vip self-update` command or any other in-tool update
  mechanism — out of scope for this issue.
