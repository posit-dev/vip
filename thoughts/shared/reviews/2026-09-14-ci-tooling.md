# Review: ci-tooling

## Summary

The pipeline itself is well-engineered: the `changes`-gated jobs, the scope-aware status aggregators, and the SHA-pinning of every external action are all deliberate and correctly documented in AGENTS.md's own inline comments. The gaps are in the surrounding tooling rather than in `ci.yml` itself. AGENTS.md's "CI workflows" section, the document this whole quality program treats as ground truth, documents only 10 of the repository's 21 workflow files, so a newcomer reading it does not know `publish.yml`, `docker.yml`, `security-audit.yml`, or `connect-integration.yml` exist. Two version pins have quietly drifted apart from the values they are supposed to track: the Dockerfile's Playwright base image is two minor versions behind the exact pin in `pyproject.toml`, and the `dev`-extra ruff range lets a plain `uv sync --all-extras` resolve a ruff two minor versions ahead of what CI and pre-commit actually enforce. `.pre-commit-config.yaml` has been sitting unreferenced and undocumented since the PR that added it. The five recipes that used to fail on a fresh clone (`just typecheck`, `just coverage`, `just test`, `just test-product`, `just report`) were already fixed on main by PR #639, so I did not re-raise them.

## Findings

### AGENTS.md documents 10 of 21 workflow files, leaving release and drift-detection workflows invisible
Severity: high
Evidence: AGENTS.md:309-320 (the `## CI workflows` section lists `ci.yml`, `preview.yml`, `pr-title.yml`, `release.yml`, the four smoke workflows as one bullet, `add-to-team-project.yml`, and `weekly-summary.yml` — 10 files)
Evidence: `ls .github/workflows/` lists 21 `.yml` files
Evidence: `grep -c 'connect-integration\|copilot-setup-steps\|docker.yml\|example-report\|install-flow-smoke\|linux-smoke\|mac-smoke\|publish\|security-audit\|website-preview\|website.yml' AGENTS.md` — all zero except an incidental match of the word "publishes" inside the `preview.yml` bullet, not a reference to `publish.yml`
Why it matters to a newcomer: The section is written as an exhaustive index ("CI workflows"), so a reader has no reason to suspect 11 files are missing. Two of the missing ones ship releases (`publish.yml` to PyPI, `docker.yml` to GHCR) and one is a nightly drift detector against real Connect (`connect-integration.yml`) that posts to Slack on failure — exactly the kind of workflow a newcomer investigating a Slack alert would need documented.
Proposed fix: Add one bullet per missing workflow to AGENTS.md's "CI workflows" section, following the existing style (trigger, purpose, anything that would surprise a reader). One line each is enough for `copilot-setup-steps.yml`, `example-report.yml` (reusable, called by the other three), `linux-smoke.yml`/`mac-smoke.yml`/`install-flow-smoke.yml` (install-flow smoke, distinct from the product smokes), `security-audit.yml`, `website.yml`/`website-preview.yml`; `connect-integration.yml`, `docker.yml`, and `publish.yml` warrant a couple of sentences each given their release-time impact.
Proposed PR: ci-tooling-docs-workflow-index (files: AGENTS.md)

### Dockerfile's Playwright base image is two minor versions behind the pinned Python package
Severity: high
Evidence: Dockerfile:3 `FROM mcr.microsoft.com/playwright/python:v1.60.0-noble`
Evidence: pyproject.toml:24 `"playwright==1.62.0",  # exact-pinned: shapes vip run output; see docs/development.md`
Evidence: `selftests/test_dependency_pins.py` enforces that the `EXACT_PINS` set (which includes `playwright`) matches `uv.lock`'s resolved version, but has no assertion about the Dockerfile's base-image tag — `grep -rln Dockerfile selftests/` returns nothing
Evidence: `.github/workflows/docker.yml` builds the image on every PR but never runs it (no `docker run` / smoke step), so a Playwright package/browser mismatch inside the image would not be caught by CI
Why it matters to a newcomer: docs/development.md's "Dependency pinning policy" section states the exact-pin invariant is enforced by a selftest, which reads as "this can't drift." The Dockerfile is a second place the same version is asserted (via the base image tag) and nothing enforces it stays in step with the first. `RUN uv sync --frozen` overwrites the base image's Playwright package with 1.62.0 while the image's baked-in browser binaries were fetched for 1.60.0; `vip install` (line 23) should reconcile this by downloading the correct browser revision, but that reconciliation is silent, untested, and wastes a browser download on every build.
Proposed fix: Bump the Dockerfile's base image tag to `v1.62.0-noble` to match the current pin, and add an assertion (either extend `test_dependency_pins.py` to read `Dockerfile`'s `FROM` line, or a short new selftest) so the two can't drift apart again silently.
Proposed PR: ci-local-parity (files: Dockerfile, selftests/test_dependency_pins.py)

### `dev`-extra ruff range lets local ruff drift from the version CI and pre-commit enforce
Severity: medium
Evidence: pyproject.toml:65 `"ruff>=0.15.0,<0.17",`
Evidence: uv.lock (resolved) — `name = "ruff"` / `version = "0.16.6"` (confirmed live: `uv run --extra dev ruff --version` → `ruff 0.16.6`)
Evidence: .github/workflows/ci.yml:59 and :65 `version: "0.15.0"` (both `astral-sh/ruff-action` steps in the `lint` job)
Evidence: .pre-commit-config.yaml:2 `rev: v0.15.0`
Why it matters to a newcomer: `just check`, `just lint`, `just fix`, and the pre-commit hook are three different ways to run "the same" check, but only pre-commit's pin matches what CI's required `Lint & Format` job actually runs. A contributor who runs `just check` locally is linting with 0.16.6; CI lints with 0.15.0. New rule defaults or bug fixes between those releases can make a PR pass locally and fail in CI, or the reverse, and CLAUDE.md's own warning ("CI pins ruff to version 0.15.0 -- do not change the version without updating .github/workflows/ci.yml") only accounts for someone editing `ci.yml` directly, not for the dev-extra range independently drifting the local tool.
Proposed fix: Tighten the `dev` extra to `ruff==0.15.0` (matching the CI/pre-commit pin exactly) so `uv sync --all-extras` and `just check` always run the same ruff CI does, or explicitly document that the ranges are allowed to diverge and why.
Proposed PR: ci-local-parity (files: pyproject.toml, uv.lock)

### `.pre-commit-config.yaml` is unreferenced and undocumented
Severity: medium
Evidence: `.pre-commit-config.yaml` full content: `repo: https://github.com/astral-sh/ruff-pre-commit`, `rev: v0.15.0`, hooks `ruff --fix` and `ruff-format`
Evidence: `git log --oneline -- .pre-commit-config.yaml` → one commit, `e7c34c2e refactor: comprehensive codebase review — bugs, dedup, API design, features, CI (#85)`, never touched since
Evidence: `grep -rln 'pre-commit' docs/ README.md AGENTS.md justfile .github/` returns nothing
Why it matters to a newcomer: The file exists and is correctly pinned to the same ruff version CI uses, so installing the hook (`pre-commit install`) would be a low-cost way to catch lint/format issues before they reach CI. Nothing tells a contributor the file exists, that it needs a one-time `pre-commit install`, or that it isn't wired into CI (no `pre-commit.ci`, no `pre-commit run --all-files` step anywhere in `.github/workflows/`). A newcomer who never stumbles on the file gets zero value from it; one who does stumble on it doesn't know whether it's load-bearing.
Proposed fix: Either document it (a short "Pre-commit hooks (optional)" subsection in docs/development.md's "Linting and formatting" section, with the `pre-commit install` command) or, if it's considered obsolete, remove it — but that's a product decision, not a call this review makes.
Proposed PR: tooling-precommit-parity (files: docs/development.md, or `.pre-commit-config.yaml` if the answer is removal)

### `just --list` shows a misleading one-line description for four recipes
Severity: low
Evidence: `just --list` output — `relock` shows description "git checkout --theirs -- uv.lock && just relock" (the last line of relock's multi-line comment, not its purpose); `mock-idp-up` and `mock-idp-saml-up` show the `/etc/hosts` line instead of "start the mock-IdP stack"; `mock-idp-totp-secret` shows the `export VIP_TEST_TOTP_SECRET=...` line instead of its purpose
Evidence: justfile's doc comments for these recipes are multi-line; `just --list` uses only the line immediately above the recipe as its description, so multi-line comments truncate to their last line
Why it matters to a newcomer: `just --list` is the first command AGENTS.md and docs/development.md both point a new contributor to. Four of its descriptions read as fragments of shell rather than as recipe summaries, which is confusing on a first pass even though the full comment (visible via `cat justfile`) is fine.
Proposed fix: Reorder each of these four recipes' comments so the one-line summary is the line immediately preceding the recipe, with supporting detail above it.
Proposed PR: ci-tooling-docs-workflow-index (files: justfile) — small enough to fold into the same PR as the AGENTS.md workflow-index fix rather than opening a fifth PR

## Proposed PRs

| slug | theme | files | estimated changed lines | depends on |
|---|---|---|---|---|
| ci-local-parity | Fix real version drift between what's pinned and what's used | Dockerfile, selftests/test_dependency_pins.py, pyproject.toml, uv.lock | ~30 | none |
| ci-tooling-docs-workflow-index | Bring AGENTS.md's workflow index and justfile's `--list` output up to date with reality | AGENTS.md, justfile | ~60 | none |
| tooling-precommit-parity | Document (or remove) the orphaned pre-commit config | docs/development.md (or `.pre-commit-config.yaml`) | ~15 | Ian's call on document-vs-remove |

## Not findings

- All external GitHub Actions across every workflow in scope are SHA-pinned; the only non-SHA `uses:` lines are local reusable-workflow/composite-action references (`./.github/workflows/example-report.yml`, `./.github/actions/notify-on-scheduled-failure`), which zizmor's `unpinned-uses` audit correctly does not flag.
- `example-report.yml` returned zero rows from `gh run list --workflow example-report.yml`. This is not evidence it never ran — it's a `workflow_call`-only reusable workflow, and `gh run list` attributes its runs to the caller (`preview.yml`/`website.yml`/`website-preview.yml`), not to itself.
- The five justfile recipes that failed on a fresh clone (`test`, `test-product`, `report` pointing at deleted `tests/`; `coverage`/`typecheck` missing `--extra dev`) were already fixed by PR #639 (`0acd0743`, closes #638). Verified live: `just typecheck` and `just selftest -x -q` both pass cleanly after a plain `uv sync` in this worktree.
- `just check` passes cleanly (ruff lint + format-check, 195 files).
- `uv build` succeeds; the wheel contains 21 force-included scaffold/report files, consistent with pyproject's `force-include` block.
- `connect-integration.yml` failed today against "Connect release" (not "preview"), but this is explicitly documented in the workflow's own header comment as a non-blocking nightly drift detector (decided in #421), and its Slack-notify job ran successfully — it is functioning as designed, not a CI-tooling defect. Worth someone's attention as a product-test finding, but out of scope here.
- `weekly-summary.yml` had one `schedule` failure on 2026-09-07 with a successful run before and after; a single non-repeating anomaly, not worth chasing given the review budget.
- `linux-smoke.yml`, `mac-smoke.yml`, and `install-flow-smoke.yml` are not duplicates of the product smoke workflows — they test `vip install`'s OS-package-detection and Chromium-provisioning code paths (RHEL/openSUSE headless smoke, macOS smoke, and the `uv tool install` PATH-topology case respectively), a genuinely different surface.
- `compose.yml`'s `${RSW_VERSION:-latest}`/`${RSC_VERSION:-latest}`/`${RSPM_VERSION:-latest}` defaults are a deliberate local-dev convenience (override via env var), not an unpinned-version bug.
- Python version matrix (3.10, 3.12) in `ci.yml` is consistent with `requires-python = ">=3.10"` and `[tool.mypy] python_version = "3.10"` (the floor is type-checked, and the matrix covers floor + a later runtime).
