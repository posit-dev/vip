# VIP code quality program: design

Date: 2026-09-14
Status: approved design, implementation plan to follow
Owner: Ian Flores Siaca

## Problem

VIP grew feature by feature. The result is a codebase that works but is hard for a newcomer to enter:

- Three modules carry most of the framework: `src/vip/auth.py` (2274 lines), `src/vip/cli.py` (2054), `src/vip/plugin.py` (1462). `src/vip_tests/workbench/conftest.py` is 1400 lines. The largest selftest file, `selftests/test_auth.py`, is 3464 lines.
- Comments narrate history instead of explaining code. A grep for "previously", "used to", "no longer", "was moved" and similar phrases finds 82 hits in `src/vip` alone. A newcomer cannot tell which of these describe current behavior.
- Error handling is inconsistent. `src/` has 129 `except Exception` blocks (33 in `auth.py`). Six custom exception classes exist (`AuthConfigError`, `AuthTimeoutError`, `ProxyConfigError`, `PlaywrightInstallError`, `PackageQueryError`, `ManifestError`) but share no base, so callers cannot catch "any VIP error" and 37 `sys.exit` calls plus three duplicated `AuthConfigError` translations decide exit codes ad hoc. Failures are hard to distinguish from one another in logs and reports.
- Static checks are thin. Ruff selects only `E`, `F`, `I`, `UP`. Mypy runs on `src/vip` only, with `ignore_missing_imports` and no strictness flags. `src/vip_tests` and `selftests` are not type-checked.
- Repository hygiene has drifted. Two root markdown files (`CHRONICLE_TEST_PLAN.md`, `IMPLEMENTATION_GUIDE.md`) are referenced nowhere. Twenty-one implementation plans for closed issues ship under `thoughts/`. `validation_docs/` holds one-off demo notes.

## Goal

Bring VIP to a state where a newcomer can read a module, understand what it does and why, trust that errors are typed and surfaced, and rely on CI to reject regressions in style, typing, and error handling. The work ships as many small draft PRs, each independently reviewable and revertable.

Done means:

1. Every review lens below has produced a findings document with `file:line` evidence.
2. Every accepted finding maps to a PR in the backlog, and every PR is either merged, open as a draft awaiting Ian's review, or explicitly deferred with a reason.
3. CI enforces every new ruff rule family and the widened mypy scope, and is green on `main`.
4. No history-narration comments remain in `src/` or `selftests/`.
5. Framework errors derive from a single `VipError` hierarchy; broad `except Exception` survives only where a comment states the concrete reason.
6. `auth.py`, `cli.py`, and `plugin.py` are packages of focused modules, each under roughly 500 lines, with unchanged public behavior confirmed by the live gate.

## Decisions already made

| Decision | Choice | Why |
|---|---|---|
| Depth | Both tiers: mechanical hygiene and structural splits | Ian chose it after the live-verification risk was raised. Structural PRs carry a hard live gate instead of being deferred. |
| Live gate for structural PRs | `just test-local-full` (Connect, Workbench, Package Manager in Docker) plus the mock IdP lanes (`just mock-idp-up`, SAML variant) | Agents can run it unattended on this Mac. Covers the auth, CLI, plugin, and client code paths that selftests only mock. |
| Approvals | Batch per wave | Ian approves the full list of PR titles and bodies once per wave. Agents use that text verbatim. Any deviation returns to Ian. |
| Lint ratchet | Enforce in CI and fix in the same PR | One PR per rule family. Nothing lands as a warning that can rot. |
| Doc hygiene | Delete shipped plans and orphan docs | History lives in git. `docs/` and `AGENTS.md` are kept and rewritten for newcomers. |
| PR form | Draft PRs only, conventional-commit titles, no AI attribution | Ian's standing rules. |
| Comment policy | One or two sentences on what and why. No change history, no issue archaeology unless the reader needs the link to act. | Ian's standing feedback rule. |

## Architecture of the program

The program has three phases. Each phase runs on sub-agents so the coordinating session keeps its context for merging, sequencing, and reporting.

### Phase 1: parallel review

Eight reviewers run concurrently, read-only, on a fresh checkout of `origin/main`. Each owns one lens and writes `thoughts/shared/reviews/2026-09-14-<lens>.md`. Reviewers use Sonnet 5.

| Lens | Scope | Questions it answers |
|---|---|---|
| comments | `src/`, `selftests/`, `examples/`, `docker/` | Which comments narrate history? Which are wrong about the code they sit on? Which docstrings are missing where the function is non-obvious? |
| error-handling | `src/vip`, `src/vip_tests` | Where does a broad except hide a real failure? Where is an error swallowed, logged and continued, or converted to a skip? Which exit paths bypass the reporter? |
| structure | `src/vip`, `src/vip_tests/**/conftest.py` | What are the natural seams in the three god-modules and the Workbench conftest? Which functions are called from only one place and belong next to their caller? Where do modules import each other in cycles? |
| typing-lint | whole Python tree | Which ruff families would fire, and how many violations each? What breaks when mypy covers `src/vip_tests` and `selftests`? Where are `Any`, untyped defs, and `type: ignore` concentrated? |
| selftests | `selftests/` | Which tests share a source of truth with the code they test? Which files should be split by subject? Which fixtures are duplicated? Where is the pytester subprocess pattern used when a direct call would do? |
| product-tests | `src/vip_tests/` | Do the seven categories follow one convention for step naming, fixtures, skips, timeouts, and selectors? Where do feature files and step definitions drift? |
| docs-hygiene | root `*.md`, `docs/`, `thoughts/`, `validation_docs/`, `presentations/`, `website/` | What is orphaned, duplicated, or stale? What does a newcomer need that is missing? Which plan files map to closed issues? |
| ci-tooling | `.github/`, `justfile`, `pyproject.toml`, `Dockerfile`, `compose*.yml`, `.pre-commit-config.yaml` | Which checks run in CI but not locally, or the reverse? Which recipes are broken or undocumented? Are pins consistent between CI and pre-commit? |

Every finding follows one format:

```
### <short title>
Severity: high | medium | low
Evidence: <path>:<line> (one or more; quote the offending line)
Why it matters to a newcomer: <one or two sentences>
Proposed fix: <one or two sentences>
Proposed PR: <slug> (files: <list>)
```

Reviewers may not propose fixes without evidence, and may not edit anything.

### Phase 2: backlog and wave planning

The coordinator merges the eight documents into `thoughts/shared/plans/2026-09-14-quality-program-backlog.md`. Merging means:

1. Deduplicate findings that two lenses reported.
2. Reject findings without evidence or that contradict a deliberate decision recorded in `AGENTS.md`, `docs/`, or a closed issue.
3. Group accepted findings into PRs. A PR has one theme and one file set. Target size is under 400 changed lines, except mechanical rule-family fixes, which may be larger but must be a single ruff family.
4. Assign each PR to a wave. Two PRs in the same wave never touch the same file. A PR that touches a file also touched by bdeitte's open PR #627 (`cli.py`, `plugin.py`, `config.py`, `gherkin.py`, the `report_*` modules, the clients) waits for #627 to merge or is written against its branch, whichever Ian prefers at the time.

Wave order and rationale:

| Wave | Theme | Why this order |
|---|---|---|
| 1 | Hygiene and ratchet: delete orphan docs and shipped plans; strip history comments; one PR per new ruff family; widen mypy scope | Cheap, mechanical, verifiable by selftests alone. Turns later findings from anecdotes into lint failures. |
| 2 | Error handling: introduce `VipError` hierarchy; narrow broad excepts module by module; route all CLI exits through one place | Depends on wave 1 lint (`BLE001`) to enumerate every site. Changes behavior, so each PR carries selftests that pin the new error type. |
| 3 | Structure: split `auth.py`, `cli.py`, `plugin.py`, Workbench `conftest.py` into packages; consolidate duplicated fixtures; split oversized selftest files by subject | Depends on wave 2 so the split modules already carry typed errors. Each PR runs the live gate. |
| 4 | Docs rewrite: `AGENTS.md`, `docs/development.md`, `docs/test-architecture.md` updated to match the new layout | Last, so it describes what exists rather than what is planned. |

Each wave ends with a batch approval: Ian sees every PR title and body, approves once, and only then do implementers commit.

### Phase 3: implementation and review

One implementer agent per PR, Sonnet 5, in its own worktree under `~/ptd-workspace/.worktrees/vip-<slug>` on a branch named `<slug>` (kebab-case, no slashes, no personal names), based on fresh `origin/main`.

Implementer protocol:

1. Read the PR entry in the backlog and the finding it resolves. Read nothing else until needed.
2. Where behavior changes, write the failing selftest first, confirm it fails for the expected reason, then implement.
3. Run in order and fix until green: `just check`, `uv run mypy` over the configured scope, `uv run pytest selftests/`, `uv run pytest src/vip_tests/ --collect-only --quiet`.
4. Wave 3 PRs additionally run `just test-local-full` and the mock IdP lanes, and paste the pytest summary lines into the PR body under a "Live gate" heading. A structural PR whose live gate is not green is not opened.
5. Commit with the approved message. Open a draft PR with the approved title and body using `gh pr create --draft`.
6. Report back: PR number, files changed, test summary, anything that deviated from the backlog entry.

Review protocol:

1. A separate reviewer agent runs the `code-review` skill at high effort on the PR diff. Findings are fixed in the same branch by the implementer. The reviewer confirms.
2. The coordinator does a final read of the diff and PR body, then reports the wave to Ian with one line per PR.

### Tracking

A continuity ledger at `thoughts/ledgers/CONTINUITY_CLAUDE-vip-quality-program.md` holds every PR as a checkbox grouped by wave, the current wave marker, open questions, and the batch-approval status. It is updated when a PR opens, passes review, or is deferred.

## Error handling design (wave 2 target)

The hierarchy is small on purpose, and it adopts the six exception classes that already exist rather than replacing them. Existing names, module locations, and the `ValueError` ancestry that fifteen selftests pin are preserved; each class gains `VipError` (or a `VipError` subclass) as an additional base.

```
VipError(Exception)                        # new, src/vip/errors.py; carries a user-facing message
  ConfigError(VipError)                    # new: vip.toml / CLI flag problems
    ProxyConfigError(ConfigError, ValueError)     # existing, proxy.py; re-parented
  AuthError(VipError)                      # new
    AuthConfigError(AuthError, ValueError)        # existing, auth.py; re-parented
      AuthTimeoutError(AuthConfigError)           # existing, unchanged
  ProductUnreachableError(VipError)        # new: network / TLS / DNS before any test runs
  InstallError(VipError)                   # new
    PlaywrightInstallError(InstallError)          # existing, install/playwright.py; re-parented
    PackageQueryError(InstallError)               # existing, install/packages.py; re-parented
    ManifestError(InstallError)                   # existing, install/manifest.py; re-parented
  ReportError(VipError)                    # new: Quarto / Typst / results.json problems
```

Rules:

- Framework code raises these. It does not call `sys.exit` or raise `SystemExit` outside the single top-level handler in `cli.py`'s `main()`, which maps `VipError` to an exit code and a one-line message. The CLI is `argparse`, not Typer; nothing in this program changes that. The three existing `AuthConfigError` translation sites (`cli.py`, two in `plugin.py`) collapse into that handler and the plugin's one auth entry point.
- Test code (`src/vip_tests`) does not catch `VipError`. It lets pytest record the failure so the report shows the real cause.
- `except Exception` survives only around third-party calls whose failure modes are genuinely unknown, and each site carries a one-line comment naming what is being tolerated and why. `BLE001` is enabled with `# noqa: BLE001` at those sites, so every remaining one is deliberate and greppable.
- Playwright `TimeoutError` and httpx errors are caught by their concrete types and re-raised as the matching `VipError` subclass with the original as `__cause__`.
- A function that today returns `None`, `False`, or an empty collection from inside an `except` block, making failure indistinguishable from "nothing found", raises instead. The Connect client's cleanup listing is the worked example.

## Structure design (wave 3 target)

Seams are proposed by the structure reviewer and confirmed in the backlog, but the intended shape is:

- `src/vip/auth/`: `__init__.py` re-exporting the current public names; `browser.py` (Chromium launch and Playwright session lifecycle); `flows.py` (`start_interactive_auth` and `start_headless_auth`, which each drive Connect and Workbench in one call and are not per-product); `workbench.py` (the only product-specific cluster: `_authenticate_workbench`, `_on_login_page`, `_wait_for_product_redirect`, `_click_workbench_oidc_confirm`); `sso.py` (OIDC and SAML shared steps); `cache.py` (saved-session load, validate, store); `apikey.py` (Connect API-key minting and probing); `totp.py` moves in. There is no Package Manager browser-auth code, so no `packagemanager.py`. The `AuthConfigError` cycle between `auth.py`, `idp.py`, and `totp.py` moves to `errors.py` in a pre-split PR.
- `src/vip/cli/`: one module per subcommand (`verify.py`, `report.py`, `install.py`, `cleanup.py`, `auth.py`, `scaffold.py`, `version.py`), plus `app.py` holding the `argparse.ArgumentParser` construction and subcommand dispatch currently in `main()`, and the single `VipError` handler.
- `src/vip/plugin/`: `hooks.py` (pytest hooks), `markers.py`, `results.py` (results.json writer), `skips.py` (version gating and if_applicable), `warnings.py`.
- `src/vip_tests/workbench/conftest.py` splits along the five clusters actually present: `login.py` (SSO, login, silent sign-in), `sessions.py` (wait, assert, state), `naming.py` (worker-owned session naming; `_VIP_OWNER_PATTERNS` in `clients/workbench.py` is updated in the same commit), `cleanup.py` (cookie-based session cleanup), `capacity.py` (profile detection). The IDE-launch skip-cascade hooks stay in `conftest.py`. There is no per-IDE fixture logic and no jobs or git code in this file. The `_on_login_page` helper duplicated between this file and `auth.py` is deduplicated first, preserving both keyword tuples; whether the conftest copy should also match `/saml/acs` is a behavior question filed as a separate issue.

Every split keeps the old import path working through `__init__.py` re-exports until the docs rewrite in wave 4, then the re-exports are pruned in a final PR.

## Testing strategy

- Selftests are the primary gate for every PR. The full suite runs on every implementer's branch, not a subset.
- Comment-only and doc-only PRs additionally run `--collect-only` to prove no import broke.
- Rule-family PRs prove the rule is enforced by leaving CI configuration and violations in the same PR: CI on the PR branch itself must be green.
- Structural PRs run the live gate described above. The mock IdP lanes cover OIDC and SAML login paths that the compose stack alone cannot.
- Every new error type has a selftest that raises it through the CLI handler and asserts the exit code and message. Tests assert independent literals, not constants imported from the code under test.

## Out of scope

- Behavior changes to product tests, new tests, or fixes to flaky tests. Those are separate issues.
- Changing the report layout or Quarto templates.
- Reworking the website under `website/`.
- Renaming public CLI flags or config keys.
- Anything in bdeitte's #627 traceability work.

## Risks

- **Silent behavior change in auth.** Mitigated by the live gate and by keeping `except` narrowing to one module per PR so a regression is bisectable.
- **Merge conflicts with #627.** Mitigated by the file-set rule in wave planning and by sequencing `cli.py` and `plugin.py` splits after #627 merges.
- **Agents exceeding scope.** Mitigated by the one-theme-one-file-set rule, the batch-approved commit text, and the independent review step.
- **Lint rule churn.** Mitigated by one family per PR, so any family that proves too noisy is reverted alone.
