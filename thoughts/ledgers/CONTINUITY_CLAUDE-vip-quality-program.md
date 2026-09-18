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
- Now: [→] RESUMED 2026-09-18 (new session, Sonnet 5). Ian approved everything and said finish wave 1, then leave a resume prompt for wave 2. Close-out commit 2abfd22c pushed; draft planning PR #701 opened. 94 leftover local worktrees found; audited, 30 confirmed-merged session worktrees + their local branches removed, 61 pre-existing unrelated worktrees left untouched. Dispatching 1.30-1.33 (mypy chain) now.
- Next (if resumed): 1.30-1.33 mypy PRs (typing-mypy-free-flags, typing-warn-unused-ignores, typing-widen-mypy-scope, typing-strict-load-engine), then waves 2-4 each with a fresh batch approval. Wave 1a: 17/18 MERGED same day; 1.7 parked on Ian's #661. Wave 1a: Batch A dispatched 2026-09-14 (1.1-1.6, 1.8-1.10). Batch B pending (1.11, 1.12, 1.14, 1.15, 1.16, 1.18). 1.13 after 1.12 merges; 1.17 after 1.16 merges; 1.7 after Ian's #661 merges.
- Next: finish 1a (#674, #676, 1.17, then 1.13; 1.7 waits on Ian's #661 and does NOT block 1b since it touches only root md files), then dispatch wave 1b chain starting with lint-ble-enable-only (1.19)
- Remaining:
  - [x] Phase 1 reviews: comments, error-handling, structure, typing-lint, selftests, product-tests, docs-hygiene, ci-tooling (75 findings, 2026-09-14)
  - [x] Phase 2: backlog merged (53 PRs: 1a 18, 1b 15, 2 11, 3 8, 4 1), check_waves OK
  - [x] Wave 1 approved by Ian ("keep going, merge as they land", 2026-09-14). Phase 2 docs committed 350d4b34, branch quality-program-design pushed; planning PR not yet opened (title/body pending Ian)
  - [x] Wave 1a: 18 of 18 PRs merged 2026-09-14 (#662-#679, #693)
  - [x] Wave 1b chain: 11/15 merged (lint complete; 4 mypy PRs deferred by Ian) (#678, #680, #682, #684-#690, #692); ALL lint PRs done; 1.30-1.33 (mypy) not dispatched, Ian asked to stop soon (23:10)
  - [ ] DEFERRED by Ian 2026-09-14: Wave 2 (11 PRs), Wave 3 (8 PRs), Wave 4 (1 PR), five GitHub issue drafts

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
| 1.30-1.33 | typing-mypy-free-flags, typing-warn-unused-ignores, typing-widen-mypy-scope, typing-strict-load-engine | | | DEFERRED (Ian stopped after #692) |

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
- Test commands: `just check`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, `uv run pytest src/vip_tests/ --collect-only --quiet`

## WAVE 1 FINAL STATE 2026-09-18

Planning close-out: commit 2abfd22c pushed, draft PR #701 opened (design/reviews/backlog/ledger). 30 leftover session worktrees + local branches removed (verified merged via `gh pr view --json state` first, not git ancestry, since this repo squash-merges); 61 pre-existing unrelated worktrees left untouched.

Mypy chain (1.30-1.33), attempted in order:
- **1.30 typing-mypy-free-flags → #702**: implemented, correct, opened draft. BLOCKED from merge (see CI-red finding below), not by anything wrong with the PR itself.
- **1.31 typing-warn-unused-ignores → #703**: implemented on top of #702's branch; corrected the approved body's stale "7 of 21 type: ignore" (current count is 7 of 17) and its Files line (actually touches pyproject.toml + kubernetes.py + plugin.py + cli.py + load_engine.py, not just kubernetes.py). Opened draft. Same BLOCKED status.
- **1.32 typing-widen-mypy-scope: NOT COMPLETED, no PR opened.** The approved body's "14 errors in 9 files" was measured against base mypy config only. Stacked on top of 1.30+1.31's new global flags (`check_untyped_defs`, `no_implicit_optional`), widening scope to `src/vip_tests`+`selftests` surfaces 187 errors in 32 files instead — those two flags apply globally and now hit untyped test doubles/fixtures that were never in scope for wave 1. Tried scoping them off for the test trees via `[[tool.mypy.overrides]]` (`module = "vip_tests.*"` worked, `module = "selftests.*"` and `module = "test_*"` did not — `selftests/` has no `__init__.py`, so mypy's dotted-module matching doesn't reach it; needs `--namespace-packages`/`explicit_package_bases`, `files=` overrides, or per-file glob investigation this session didn't have budget for). Abandoned uncommitted in a disposable worktree, now removed; no data lost, nothing pushed.
- **1.33 typing-strict-load-engine: NOT STARTED** (depends on 1.32). Already corrected in the approval file from a stale "81 errors" claim to the real current count of 27 (measured 2026-09-18) and the Files line expanded to include pyproject.toml + load_engine.py (was load_users.py only).

## BLOCKER: CI is red on main, unrelated to this program
`origin/main` at `a449a98b` fails ruff (`Lint & Format`, a required check) with 20 hits (17 D209, 2 D413, 1 RUF001) in `selftests/test_workbench_exec.py`, `selftests/test_plugin.py`, `src/vip_tests/workbench/exec.py`. Root cause: Ian's own PR #681 ("fix(workbench): deliver RStudio console commands atomically") added docstrings/strings after wave-1's lint ratchet landed that don't comply with it (19 of 20 are `--fix`-able). Confirmed via `gh pr view 702 --json statusCheckRollup`: `Lint & Format` = FAILURE, `mergeStateStatus` = BLOCKED. This blocks a normal merge of #702, #703, and any future wave-1/2/3 PR until fixed — not something I fixed unilaterally since it's outside wave 1's approved backlog and touches Ian's own PR's files; needs his decision (see final report).

## INCIDENT (see above, 2026-09-18): recovered, feedback filed, memory updated. No data confirmed lost; branch fix-rstudio-console-delivery-603 fully restored to its own HEAD.
