# Continuity Ledger: vip-quality-program

## Goal
Bring posit-dev/vip to newcomer-readable, typed-error, CI-enforced quality via many small draft PRs. Done when every item in the design doc's "Done means" list holds. Design: thoughts/shared/plans/2026-09-14-quality-program-design.md. Plan: thoughts/shared/plans/2026-09-14-quality-program-phase1-plan.md.

## Constraints
- Draft PRs only. No AI attribution. Batch approval of PR titles and bodies per wave.
- Branch names kebab-case, no slashes, no personal names. One worktree per PR under ~/ptd-workspace/.worktrees/vip-<slug>.
- Wave 3 (structural) PRs must pass `just test-local-full` and the mock IdP lanes before opening.
- Files touched by open PR #627 (cli.py, plugin.py, config.py, gherkin.py, report_*.py, clients/*) are sequenced after #627 merges unless Ian says otherwise.

## Key Decisions
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
- Now: [→] Wave 1 approval by Ian (package: thoughts/shared/plans/2026-09-14-wave1-approval.md, 33 entries; pending commit of phase 2 docs)
- Next: Wave 1a dispatch (18 parallel implementers), then 1b chain (15)
- Remaining:
  - [x] Phase 1 reviews: comments, error-handling, structure, typing-lint, selftests, product-tests, docs-hygiene, ci-tooling (75 findings, 2026-09-14)
  - [x] Phase 2: backlog merged (53 PRs: 1a 18, 1b 15, 2 11, 3 8, 4 1), check_waves OK
  - [ ] Wave 1 approved by Ian
  - [ ] Wave 1 PRs open and reviewed
  - [ ] Wave 2 approved / open / reviewed
  - [ ] Wave 3 approved / open / live-gated / reviewed
  - [ ] Wave 4 approved / open / reviewed

## Open Questions
- UNCONFIRMED: should workbench/conftest.py's `_on_login_page` also match `/saml/acs` like auth.py's copy (structure review found the #263 fix landed in one copy only)? Behavior change; needs Ian.
- UNCONFIRMED: does wave 3 wait for #627 to merge, or build on its branch? (Wave 1 comment PRs: decided, proceed on main.)

## Working Set
- Worktree: ~/ptd-workspace/.worktrees/vip-quality-program (branch quality-program-design)
- Reviews: thoughts/shared/reviews/2026-09-14-*.md
- Backlog: thoughts/shared/plans/2026-09-14-quality-program-backlog.md
- Baseline: selftests 1951 passed / 3 skipped on ff81793d
- Test commands: `just check`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, `uv run pytest src/vip_tests/ --collect-only --quiet`
