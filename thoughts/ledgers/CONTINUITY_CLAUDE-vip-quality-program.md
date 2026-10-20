# Continuity Ledger: vip-quality-program

## Goal
Bring posit-dev/vip to newcomer-readable, typed-error, CI-enforced quality via many small draft PRs. Done when every item in the design doc's "Done means" list holds. Design: thoughts/shared/plans/2026-09-14-quality-program-design.md. Plan: thoughts/shared/plans/2026-09-14-quality-program-phase1-plan.md.

## Constraints
- Draft PRs only. No AI attribution. Batch approval of PR titles and bodies per wave.
- Branch names kebab-case, no slashes, no personal names. One worktree per PR under ~/ptd-workspace/.worktrees/vip-<slug>.
- Wave 3 (structural) PRs must pass `just test-local-full` and the mock IdP lanes before opening.
- Files touched by open PR #627 (cli.py, plugin.py, config.py, gherkin.py, report_*.py, clients/*) are sequenced after #627 merges unless Ian says otherwise.

## Key Decisions
- Ian: STOP AFTER WAVE 1 (2026-09-14, ~21:00). Finish 1.27-1.33, merge 1.7 when #661 lands and #683 when #656 lands, then close out. Waves 2-4 (20 PRs) and the five drafted GitHub issues stay in the backlog and approval file as deferred work; nothing from them is dispatched.
- 2026-09-14 15:08: Ian merged his own #656 (ruff pin), #657, #658 and pushed f71ce9f5 directly; 22:09 merged #661. These unblocked #683 and 1.7.
- Ian authorized squash-merging wave 1 PRs into main as each passes independent review and CI ("merge as they land", 2026-09-14). Repo is squash-only with delete-branch-on-merge. Required checks: CI Status, Lint & Format, Selftests Status, check-title, and the Connect/PM/Workbench smoke statuses and Mock-IdP E2E Status.
- Both tiers (mechanical and structural) run on agents. Ian chose this after the live-verification risk was raised. 2026-09-14.
- Live gate is local compose plus mock IdP, not dev.current.posit.team. 2026-09-14.
- Lint ratchet is enforce-and-fix per family, one PR each. 2026-09-14.
- Shipped plans under thoughts/ and orphan root docs are deleted, not archived. 2026-09-14.
- Wave 1b: the eight ≤20-line ruff families are bundled into one `lint-small-families` PR; big families and mypy flags stay one PR each. Chain ~15 PRs. 2026-09-14.
- The two silent-failure product-test bugs (VS Code false skip, TLS verify as plain skip) get GitHub issues AND wave 2 fix PRs, overriding the "no product-test behavior change" scope line for these two. 2026-09-14.
- Comment-only and docstring-only PRs proceed on main now and rebase if #627/#658 land first; wave 2/3 still wait for #627. 2026-09-14.
- docs/ redirect stubs: delete. .pre-commit-config.yaml: keep and document in docs/development.md. 2026-09-14.
- Design doc corrected 2026-09-14 from review evidence: CLI is argparse not Typer; six exception classes already exist and are re-parented; no packagemanager.py in auth split; workbench conftest splits login/sessions/naming/cleanup/capacity.

## State
- Done:
  - [x] Design spec committed (dbbdfb32)
  - [x] Wave 1 FULLY COMPLETE 2026-09-21: 1.30-1.33 merged (#702, #703, #705, #706). All 53 wave-1 backlog PRs now landed.
- Now: [→] RESUMED 2026-09-21. Ian approved (1) the #703 fix, (2) merging #702/#703 once green, (3) proceeding with 1.32/1.33, (4) the wave 2 batch — all "yes". Wave 2 approved but not yet dispatched; 2.1 errors-hierarchy must land first (see "Wave 2 approval: APPROVED" section above).
- Next: dispatch wave 2, starting with 2.1 errors-hierarchy (everything else in wave 2 except 2.10/2.11 depends on it; those two are independent and can start anytime).
- Remaining:
  - [x] Phase 1 reviews: comments, error-handling, structure, typing-lint, selftests, product-tests, docs-hygiene, ci-tooling (75 findings, 2026-09-14)
  - [x] Phase 2: backlog merged (53 PRs: 1a 18, 1b 15 including the mypy chain), check_waves OK
  - [x] Wave 1 approved by Ian ("keep going, merge as they land", 2026-09-14)
  - [x] Wave 1a: 18 of 18 PRs merged 2026-09-14 (#662-#679, #693)
  - [x] Wave 1b chain: 15 of 15 merged — lint families 2026-09-14/18 (#678, #680, #682, #684-#690, #692), mypy chain 2026-09-18/21 (#702, #703, #705, #706)
  - [ ] APPROVED, not dispatched: Wave 2 (11 PRs, error handling)
  - [ ] DEFERRED, no fresh approval yet: Wave 3 (8 PRs, structure), Wave 4 (1 PR, docs), five GitHub issue drafts

## Wave 1a PR tracker
| row | slug | PR | review | state |
|---|---|---|---|---|
| 1.1 | comments-cli | #664 | approve | MERGED a9972605 |
| 1.2 | comments-fixtures-proxy-plugin | #674 | approve (body amended: plugin.py dropped) | MERGED 5afccb72 |
| 1.3 | comments-rationale-auth | #667 | approve | MERGED bb3eb68a |
| 1.4 | comments-strip-history-other | #665 | approve | MERGED 8d6d2c61 |
| 1.5 | docstrings-install | #669 | approve after fix | MERGED ccb1c752 |
| 1.6 | docstrings-config | #666 | approve after fix | MERGED b09f5e1b |
| 1.7 | docs-remove-orphan-root-files | #693 | coordinator-reviewed (deletion-only, 0 refs); body tense fixed | MERGED aef8d8e4 |
| 1.8 | docs-remove-shipped-plans | #663 | fix confirmed by code-review finding text; body amended | MERGED 2053538c |
| 1.9 | docs-remove-validation-docs | #662 | clean | MERGED f79b9930 |
| 1.10 | docs-remove-orphan-redirect-stubs | #668 | clean | MERGED 7c4909e7 |
| 1.11 | docs-fix-stale-references | #670 | approve after fix (line 35) | MERGED 3fce8887 |
| 1.12 | ci-tooling-docs-workflow-index | #676 | approve after fix | MERGED 2ada5402 |
| 1.13 | product-tests-category-docs | #679 | approve | MERGED 637d81e1 |
| 1.14 | tooling-precommit-parity | #672 | approve | MERGED 7b76e9d3 |
| 1.15 | ci-local-parity | #675 | approve | MERGED 25b941fa |
| 1.16 | comments-tests-workbench-cleanup | #671 | approve | MERGED f547906d |
| 1.17 | product-tests-k8s-fixture-inventory-doc | #677 | approve after fix (purpose wording restored) | MERGED b9f0f8dc |
| 1.18 | selftests-drift-guard-comment | #673 | approve | MERGED 7d027b90 |

Approved-text amendments (flag to Ian): entry 1.2 body/files dropped plugin.py; entry 1.8 body gained a third paragraph about the mock-idp-e2e.yml comment fix; entry 1.22 body paragraph 1 rewritten because PERF203 is ignored-with-reason; entry 1.23 count 71→66; entry 1.24 body rewritten because SIM105 is deferred to after wave 2 (would erase BLE001 markers); 1.27 'four directories'→'repository'; 1.28 count 92→90; 1.29 body rewritten (stale claim about test_auth_tls_e2e.py blanket noqas, already removed in #680) and title two→14, six→seven ClassVar; 1.34 body gained a third paragraph (stale AGENTS.md rule list → pointer) rather than 'fixed' (restructuring try/except-in-loop changes behavior). Both applied to the PRs and to the approval file.

Notes: a stale `+refs/heads/auth-cache-validation` fetch refspec in the shared .git/config broke `git fetch origin` for every worktree; an implementer removed it (default main refspec restored). `gh pr create` inside these worktrees needs explicit `--head <branch> --base main`. The forked code-review on #668 ran `git checkout origin/<branch> -- .` in the planning worktree and briefly clobbered this ledger; restored. Do not run code-review forks with the planning worktree as cwd.

## Wave 1b PR tracker (sequential chain; each rebases on the previous)
| row | slug | PR | review | state |
|---|---|---|---|---|
| 1.19 | lint-ble-enable-only | #678 | approve (121 pairs verified mechanical) | MERGED ab774138 |
| 1.20 | lint-small-families | #680 | approve; CI fixed (scripts/ S101) | MERGED 67cc39fd |
| 1.21 | lint-pth | #682 | approve; macOS flake rerun green | MERGED aeed7580 |
| 1.34 | ci-lint-repo-root | #683 | coordinator-reviewed; local `just check` now == CI scope; stale rule list → pointer | MERGED d9386b99 |
| 1.22 | lint-perf | #684 | approve | MERGED 570c283f |
| 1.23 | lint-pt | #685 | approve | MERGED 1110d97e |
| 1.24 | lint-sim | #686 | approve | MERGED d413334e |
| 1.25 | lint-pl-subset | #687 | approve | MERGED c1539943 |
| 1.26 | lint-arg-vip-only | #688 | coordinator-reviewed (8-line diff) | MERGED ba525fdb |
| 1.27 | lint-d-formatting | #689 | approve (AST proof: 2421 docstrings, 10 D403 diffs only) | MERGED d20777f9 |
| 1.28 | lint-d-vip-docstrings | #690 | approve (90/90 verified) | MERGED 4d59e309 |
| 1.29 | lint-ruf-unused-noqa | #692 | approve | MERGED 6c736edc |
| 1.30 | typing-mypy-free-flags | #702 | coordinator-reviewed (2-line pyproject.toml diff) | MERGED 2026-09-21 |
| 1.31 | typing-warn-unused-ignores | #703 | coordinator-reviewed; caught 1 real regression (see below) before merge | MERGED 2026-09-21 |
| 1.32 | typing-widen-mypy-scope | #705 | 2 independent /code-review passes; 3 real findings fixed (see below) | MERGED 2026-09-21 |
| 1.33 | typing-strict-load-engine | #706 | 1 /code-review pass; 2 real findings fixed (see below) | MERGED 2026-09-21 |

## Open Questions
- Wave 4 docs rewrite must update AGENTS.md's 'Ruff rules: E, F, I, UP' sentence (now BLE, B, C4, ISC, N, PGH, PIE, PTH, RET, S101, TID, + later families) and docs/development.md:35-38's four-directory ruff commands (same stale list #683 fixes in AGENTS.md/justfile).
- FLAKE (selftests, 2026-09-14): selftests/test_workbench_cleanup.py::test_quit_vip_sessions_no_warning_when_fully_cleaned asserts `not caplog.records` on the global logger; on macOS 3.10 a Playwright `Connection.run` task from a neighbouring test logged "Task was destroyed but it is pending" into its capture. Fix belongs to the selftests lens (scope caplog to the `vip` logger, or filter asyncio). Add to backlog as a wave 3 selftests row or file an issue.
- FINDING (ci-tooling gap, 2026-09-14): astral-sh/ruff-action appends the repo root to `args`, so CI lints scripts/ (and everything) while justfile/AGENTS.md/pre-commit lint only src/ selftests/ examples/ docker/. Every wave 1b implementer must verify with `uvx ruff@0.15.0 check .` from the repo root. Follow-up PR approved by Ian → entry 1.34 ci-lint-repo-root.
- UNCONFIRMED: should workbench/conftest.py's `_on_login_page` also match `/saml/acs` like auth.py's copy (structure review found the #263 fix landed in one copy only)? Behavior change; needs Ian.
- UNCONFIRMED: does wave 3 wait for #627 to merge, or build on its branch? (Wave 1 comment PRs: decided, proceed on main.)

## Working Set
- Worktree: ~/ptd-workspace/.worktrees/vip-quality-program (branch quality-program-design)
- Reviews: thoughts/shared/reviews/2026-09-14-*.md
- Backlog: thoughts/shared/plans/2026-09-14-quality-program-backlog.md
- Baseline: selftests 1951/3 on ff81793d; 1952/3 after #675; 1984/3 on f71ce9f5 (Ian merged #656/#657/#658 at 15:08 and pushed a D209 fix f71ce9f5; #658 brought 32 selftests)
- Test commands: `just check`, `uv run --all-extras mypy src/vip src/vip_tests selftests` (post-1.32/1.33; `--extra dev` alone misses locust-import errors in load_engine.py), `uv run pytest selftests/`, `uv run pytest src/vip_tests/ --collect-only --quiet`

## WAVE 1 FINAL STATE 2026-09-18

Planning close-out: commit 2abfd22c pushed, draft PR #701 opened (design/reviews/backlog/ledger). 30 leftover session worktrees + local branches removed (verified merged via `gh pr view --json state` first, not git ancestry, since this repo squash-merges); 61 pre-existing unrelated worktrees left untouched.

## MYPY CHAIN (1.30-1.33): COMPLETE 2026-09-21

Resumed 2026-09-21. Root cause of the 1.32 blocker found: `selftests/` has no `__init__.py`, so without `explicit_package_bases = true` + `namespace_packages = true` in `[tool.mypy]`, mypy assigns files there a bare module name (no `selftests.` prefix) — that's why `module = "selftests.*"` never matched. Fixed by adding those two settings plus `mypy_path = "src"`, which also required `[[tool.mypy.overrides]] module = ["vip_tests.*", "selftests.*"] check_untyped_defs = false` to keep the widened scope cheap (real bugs only) instead of surfacing ~188 errors of untyped test-double/fixture noise from 1.30/1.31's new global flags.

- **1.30 → #702, 1.31 → #703**: unblocked by rebasing (merge commits, not force-push — the global no-force-push rule caught an initial `git rebase` attempt) onto main once Ian's own #704 fixed the #681 lint regression that had been blocking them. #703's fresh CI (with `uv sync --all-extras`, unlike a `--extra dev`-only local run) caught a real regression: 1.31 had deleted a genuinely-needed `env._vip_credentials = ...  # type: ignore[attr-defined]` in `load_engine.py`, masked locally because `locust` (the `load` extra) wasn't installed. Restored with Ian's explicit approval of the commit message, both merged.
- **1.32 → #705**: implemented per the root-cause fix above; real error count after correctly scoping the override was 22 across 12 files (not the approved body's stale "14 in 9", which predated 1.30/1.31's flags). Also fixed `just typecheck` to `--all-extras` (it was `--extra dev`, the same locust-masking gap that hit 1.31). **Incident**: a backgrounded `/code-review` fork reviewing this PR ran its live-verification edits in a *different*, unrelated worktree (`vip-typing-strict-load-engine`, 1.33's worktree) instead of this one — caught because a `git add -A` in that worktree vacuumed up the stray edit into a 1.33 commit; fixed with a follow-up commit there, feedback filed. The review (redone once contamination was fixed) then found 3 real issues in #705 itself: 3 more unguarded `Manifest | None` call sites in `test_runner.py` (same bug class already partially fixed, missed instances); a no-op `no_implicit_optional = false` half of the override (dropped); `test_session_capacity.py`'s `dict[str, str | None]` conflating two different-nullability fields (replaced with a `LaunchedSession` TypedDict). All fixed before merge.
- **1.33 → #706**: strict flags (`disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`) scoped to `vip.load_engine`/`vip.load_users` via per-module override; real count was 27 (matching the approval file's already-corrected figure). A second independent review found 2 more real issues: removing `_wb_cleanup_state`'s `type: ignore` in 1.32 wasn't a real fix since the function was untyped and the widened-scope override skipped its body entirely (silently unchecked) — fixed properly by fully typing the fixture chain (`_wb_cleanup_state`/`_run_session_cleanup`/`_cleanup_sessions`) with a new `_WbCleanupState` TypedDict, confirmed by deliberately breaking the type and watching mypy catch it; and `docs/development.md` still documented the pre-1.32 mypy command (violates the "check .md files, update if necessary" rule) — updated.

Both reviews independently confirmed the known macOS flake in `selftests/test_workbench_cleanup.py` (caplog/Playwright `Connection.run` interaction) — clean on rerun each time, not a regression.

## BLOCKER: RESOLVED 2026-09-21
Ian had already merged `fix(lint): repair the D209/D413 violations #681 landed on main (#704)` on 2026-09-19; main is green again (verified `uvx ruff@0.15.0 check .` clean on origin/main 75878c50). Resumed 2026-09-21: rebased #702 and #703 onto current main via merge commits (never force-pushed — the global no-force-push rule caught an initial `git rebase` attempt; reset to the pushed tip and merged origin/main in instead, both fast-forward pushes). #702 green. #703's fresh CI (with `uv sync --all-extras`, unlike my local venv) caught a real regression 1.31 introduced: it deleted `env._vip_credentials = ...  # type: ignore[attr-defined]` in `load_engine.py:376` as "unused" based on a local mypy run where the `locust` extra wasn't installed (`ignore_missing_imports` masked the real error). Restored the ignore, commit `0c9a1bd2` (Ian approved the message), pushed. Ian approved: (1) that commit, (2) merging #702/#703 once green, (3) proceeding with 1.32/1.33, (4) the wave 2 batch below — all four "yes" 2026-09-21.

## Mypy `selftests.*` override root cause: FOUND 2026-09-21
`selftests/` has no `__init__.py`. Without `explicit_package_bases = true` + `namespace_packages = true` in `[tool.mypy]`, mypy assigns a bare module name (`test_workbench_cleanup`, no `selftests.` prefix) to files there, so `module = "selftests.*"` in `[[tool.mypy.overrides]]` never matches anything. Verified via `--verbose` (`BuildSource(... module='test_workbench_cleanup')` without the flags vs `module='selftests.test_workbench_cleanup'` with them). Fix: add both flags to `[tool.mypy]` in 1.32; then `module = "selftests.*"` and `module = "vip_tests.*"` overrides both work. Unblocks 1.32 and 1.33.

## Wave 2 approval: APPROVED 2026-09-21
Drafted `thoughts/shared/plans/2026-09-14-wave2-approval.md` (11 PRs, error-handling wave, grounded in the actual error-handling/product-tests review findings — e.g. `errors-hierarchy` reconciles with the pre-existing `AuthConfigError` rather than replacing it, corrects the design doc's Typer assumption to argparse's `args.func(args)` dispatch). Ian approved as drafted, 2026-09-21. Not yet dispatched — 2.1 `errors-hierarchy` must land first (everything except 2.10/2.11 depends on it); 2.10/2.11 are independent and can start anytime.

## INCIDENT (2026-09-18): recovered, feedback filed, memory updated. No data confirmed lost; branch fix-rstudio-console-delivery-603 fully restored to its own HEAD.
