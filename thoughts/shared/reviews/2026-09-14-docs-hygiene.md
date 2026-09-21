# Review: docs-hygiene

## Summary

The repository carries real dead weight: two orphan root files, twenty shipped implementation plans for issues that are all now closed or merged, two showboat demo transcripts for closed issues, and six one-line redirect stubs under `docs/` that nothing links to. Two of these findings are new relative to the design doc's own inventory: five `docs/*.md` files are redirect-only stubs that break the file-based newcomer path (the design doc names only the two root orphans), and both extension example READMEs document a `vip verify` invocation that fails on a fresh copy-paste because it omits the `--` pytest-arg separator. `AGENTS.md` and `.claude/agents/test-architect.md` have also drifted from the code: the agent file tells a reader to reuse fixtures and Given-steps from `src/vip_tests/conftest.py`, which no longer holds any, and to use bare `pytest.skip()` where `AGENTS.md` itself now mandates `vip.attest`. `AGENTS.md` documents neither a comment policy nor an error-handling policy, which the quality program is about to need. For a newcomer, the two most consequential findings are the broken example command and the dead-end `docs/getting-started.md` stub; the rest is safe, mechanical deletion.

## Findings

### Two root markdown files are orphaned and one says it shouldn't be committed
Severity: high
Evidence: CHRONICLE_TEST_PLAN.md:2 `Working/scratch doc (not for commit). Goal: validate the` \`feat/chronicle-tests\` `branch against a real Workbench with Chronicle enabled.`
Evidence: IMPLEMENTATION_GUIDE.md:1 `# VIP Implementation Guide`
Why it matters to a newcomer: Both sit at the repo root next to `README.md` and `AGENTS.md`, so they read as current onboarding material; `CHRONICLE_TEST_PLAN.md` explicitly documents itself as a scratch file that should never have been committed.
Proposed fix: Delete both; history is preserved in git (`d912850d`, `3eb3d71c`).
Proposed PR: docs-remove-orphan-root-files (files: CHRONICLE_TEST_PLAN.md, IMPLEMENTATION_GUIDE.md)

### Twenty implementation plans under thoughts/ target closed or merged work
Severity: high
Evidence: thoughts/shared/plans/2026-05-29-issue-298-custom-test-scaffolding.md — issue #298, `gh issue view 298` → `CLOSED [Feature] add example of adding a custom test extension`
Evidence: thoughts/shared/plans/2026-07-20-issue-484-workbench-parallel-plan.md — issue #484, `CLOSED test(workbench): parallelize tests by IDE type instead of forcing serial`
Evidence: thoughts/shared/plans/2026-07-21-issue-149-ci-integration-plan.md — issue #149, `CLOSED feat: CI pipeline integration (container image + machine-readable output)`
Evidence: thoughts/shared/plans/2026-08-21-example-report-improvements.md — no issue number in the name, but its own text names the PR: line 1 `# Example Validation Report — improvements`, matched via `git log` to commit `3eb3d71c fix(report): repair the example validation report end to end (#607)`, `gh issue view 607` → `MERGED`
Evidence: run `for n in 298 301 302 303 304 305 306 307 308 288 344 409 410 411 430 484 149; do gh issue view "$n" -R posit-dev/vip --json state,title -q '"\(.state) \(.title)"'; done` to confirm all fifteen remaining issue numbers are `CLOSED`
Why it matters to a newcomer: A reader who opens `thoughts/shared/plans/` to understand "what's being worked on" finds twenty files, all of which describe finished work, with no marker distinguishing them from the two live plans that belong to this quality program.
Proposed fix: Delete all twenty files in one PR; the design doc already calls this "shipped plans," and history lives in git.
Proposed PR: docs-remove-shipped-plans (files: thoughts/shared/plans/2026-05-29-issue-298-custom-test-scaffolding.md, thoughts/shared/plans/2026-05-29-issue-301-workbench-in-session-execution.md, thoughts/shared/plans/2026-05-29-issue-302-workbench-jobs.md, thoughts/shared/plans/2026-05-29-issue-303-workbench-runtime-versions.md, thoughts/shared/plans/2026-05-29-issue-304-k8s-autoscaling-probes.md, thoughts/shared/plans/2026-05-29-issue-305-workbench-idle-session-auto-suspend.md, thoughts/shared/plans/2026-05-29-issue-306-workbench-git-ops.md, thoughts/shared/plans/2026-05-29-issue-307-workbench-to-connect-publishing.md, thoughts/shared/plans/2026-05-29-issue-308-workbench-small-gaps.md, thoughts/shared/plans/2026-06-01-issue-288-timeout-configuration.md, thoughts/shared/plans/2026-06-05-issue-344-error-summary-line-breaks.md, thoughts/shared/plans/2026-06-30-issue-409-robust-cicd-design.md, thoughts/shared/plans/2026-06-30-issue-410-better-version-gating-design.md, thoughts/shared/plans/2026-06-30-issue-411-remove-shiny-k8s-modes-design.md, thoughts/shared/plans/2026-07-08-issue-430-interactive-auth-headless-only.md, thoughts/shared/plans/2026-07-20-issue-484-workbench-parallel-design.md, thoughts/shared/plans/2026-07-20-issue-484-workbench-parallel-plan.md, thoughts/shared/plans/2026-07-21-issue-149-ci-integration-design.md, thoughts/shared/plans/2026-07-21-issue-149-ci-integration-plan.md, thoughts/shared/plans/2026-08-21-example-report-improvements.md)

### Both extension-example READMEs document a vip verify command that fails as written
Severity: high
Evidence: examples/custom_tests/README.md:26 `vip verify --config vip.toml --extensions . --collect-only`
Evidence: examples/cross_product_validation/README.md:31 `vip verify --config vip.toml --extensions . --collect-only`
Evidence: reproduced live: `uv run vip verify --config vip.toml.example --extensions examples/custom_tests --collect-only` → `vip: error: unrecognized arguments: --collect-only`
Evidence: AGENTS.md:80 shows the correct form for the same intent: `uv run vip verify --config vip.toml --categories package-manager -- -v`
Why it matters to a newcomer: This is the literal "dry-run: collect tests without executing" line in both example READMEs — exactly the command a newcomer copies first to sanity-check a new extension before running it for real, and it errors immediately with no hint about the missing `--` pytest-arg separator that `vip verify --help` documents.
Proposed fix: Change both to `vip verify --config vip.toml --extensions . -- --collect-only`.
Proposed PR: docs-fix-stale-references (files: examples/custom_tests/README.md, examples/cross_product_validation/README.md, .claude/agents/test-architect.md, presentations/se-overview/index.qmd)

### .claude/agents/test-architect.md points at a fixture location that no longer holds any Given-steps or fixtures
Severity: high
Evidence: .claude/agents/test-architect.md:27 `- Reuse existing Given steps from \`src/vip_tests/conftest.py\` for common guards`
Evidence: .claude/agents/test-architect.md:67 `- Fixtures are defined in \`src/vip_tests/conftest.py\` (session-scoped) and available everywhere.`
Evidence: `grep -n "^@given|^def " src/vip_tests/conftest.py` shows only three autouse cleanup fixtures (`_connect_created_guids`, `_connect_content_cleanup`, `_connect_end_of_run_sweep`), zero `@given` steps
Evidence: AGENTS.md's own key-source-files table documents the move: `src/vip/fixtures.py` — "VIP's core pytest fixtures and shared BDD 'Given' steps... registered by \`vip.plugin.pytest_configure\` rather than defined in a \`conftest.py\`... (issue #609)"
Why it matters to a newcomer: This is the one file in the repo whose explicit job is to guide a human or AI agent through writing a new test. Following it sends the reader hunting for fixtures in a file that AGENTS.md documents as deliberately emptied of them for issue #609, wasting the exact effort the file exists to save.
Proposed fix: Update both lines to point at `src/vip/fixtures.py`, matching AGENTS.md's own description.
Proposed PR: docs-fix-stale-references (see file list above)

### .claude/agents/test-architect.md tells agents to use bare pytest.skip(), contradicting AGENTS.md's documented policy
Severity: high
Evidence: .claude/agents/test-architect.md:66 `- Use \`pytest.skip("reason")\` in Given steps when preconditions aren't met -- don't use assertions, which produce confusing failures instead of clean skips.`
Evidence: AGENTS.md:391-392 (Common mistakes to avoid) states the opposite: a bare `pytest.skip()` in a tracked file is a build failure, and "the real situation is 'I could not check this'... use \`vip.attest.unproven()\`"
Why it matters to a newcomer: An agent (this repo ships this file specifically to brief Claude Code) following test-architect.md's instruction verbatim will write code that `selftests/test_skip_triage.py` rejects, or worse, silently pass a check that was never actually run — precisely the failure mode issue #616 was filed to close.
Proposed fix: Replace the line with guidance to use `vip.attest.not_applicable()` / `vip.attest.unproven()`, matching AGENTS.md.
Proposed PR: docs-fix-stale-references (see file list above)

### AGENTS.md documents no comment policy and no error-handling policy
Severity: high
Evidence: `grep -n -i "comment polic\|error handling\|except Exception\|VipError" AGENTS.md` → zero matches
Why it matters to a newcomer: The design doc this review feeds identifies exactly these two gaps as root problems (history-narration comments, untyped `except Exception`), and the quality program's wave 2 is about to introduce a `VipError` hierarchy and a comment standard. A newcomer reading AGENTS.md today has no way to learn either convention, and once wave 2/3 land, AGENTS.md will be silently wrong rather than merely silent.
Proposed fix: Wave 4 rewrite must add a "Comment policy" and an "Error handling" section to AGENTS.md once the `VipError` hierarchy exists.
Proposed PR: docs-newcomer-rewrite (wave 4; see outline below)

### Six docs/*.md files are pure redirect stubs, unlinked from anywhere in the repo or website
Severity: medium
Evidence: docs/getting-started.md:3 `This documentation has moved to the VIP website:`
Evidence: docs/authentication.md:3, docs/configuration.md:3, docs/deployment-verification.md:3, docs/test-categories.md:3, docs/reporting.md:3 — identical pattern, confirmed via `grep -n "This documentation has moved" docs/*.md`
Evidence: `git ls-files '*.md' | grep -v '^website/' | while read f; do n=$(git grep -l "$(basename "$f")" -- . ":!$f" | wc -l); echo "$n $f"; done | sort -n` shows `0` for all six; `README.md` links only `docs/development.md` and `docs/test-architecture.md` (`grep -n "docs/" README.md`), and the website's own Getting Started page is a hand-authored Astro page (`website/src/pages/getting-started.astro`), not generated from these files
Why it matters to a newcomer: This review's own instructions had the newcomer path go README → `docs/getting-started.md` → `docs/development.md`, on the reasonable assumption that a file named `getting-started.md` has content. It has one link and no local instructions. Nothing in `docs/`, `README.md`, or `AGENTS.md` says "the real getting-started content lives in `website/`, only development.md and test-architecture.md are current here" — the reader has to discover that by opening the file.
Proposed fix: Delete all six stubs (git history + the external website already carry this content), or replace them with a single `docs/README.md` index stating the docs/ vs website/ split explicitly. Either way this is a docs-hygiene decision the design doc didn't anticipate (it names only the two root files); flag for Ian's confirmation before deleting, since the stubs may exist to catch old bookmarked GitHub links.
Proposed PR: docs-remove-orphan-redirect-stubs (files: docs/authentication.md, docs/configuration.md, docs/deployment-verification.md, docs/getting-started.md, docs/test-categories.md, docs/reporting.md)

### validation_docs/ holds two showboat transcripts for closed issues
Severity: medium
Evidence: validation_docs/demo-477-positron-console.md:1 `# fix(workbench): Positron console launch gate (#477)` — `gh issue view 477` → `CLOSED`
Evidence: validation_docs/demo-workbench-parallel-484.md:1 `# feat(workbench): parallelize BDD suite under shared auth (#484)` — `gh issue view 484` → `CLOSED`
Why it matters to a newcomer: Same shape as the shipped-plans problem: these are Showboat-generated live-diagnosis transcripts for work that has already merged, sitting in a directory a newcomer might mistake for a live validation-in-progress log.
Proposed fix: Delete both.
Proposed PR: docs-remove-validation-docs (files: validation_docs/demo-477-positron-console.md, validation_docs/demo-workbench-parallel-484.md)

### se-overview presentation still advertises a removed `vip app` Shiny UI
Severity: medium
Evidence: presentations/se-overview/index.qmd:59 `**Shiny app:**`
Evidence: presentations/se-overview/index.qmd:66 `...vip app gives you a Shiny UI if you'd rather click than type...`
Evidence: `uv run vip --help` command list is `{version,auth,verify,cleanup,install,uninstall,report,status,scaffold}` — no `app` subcommand; issue #411 "Remove Shiny and Kubernetes modes" is `CLOSED` (`gh issue view 411`)
Why it matters to a newcomer: This deck is used live with SEs and customers (per its directory name); anyone demoing `vip app` from it will get a CLI error in front of an audience, and the deck otherwise looks current (it separately cites Connect 2026.06.0, a recent version).
Proposed fix: Remove the Shiny-app bullet and its follow-on sentence.
Proposed PR: docs-fix-stale-references (see file list above)

### AGENTS.md and docs/development.md duplicate the ruff lint/format instructions
Severity: low
Evidence: AGENTS.md:24 `## Code quality` through AGENTS.md:31 `uv run ruff format --check src/ selftests/ examples/ docker/` duplicates docs/development.md:16 `## Linting and formatting` through docs/development.md:39, both giving `uv run ruff check`, `uv run ruff format --check`, `just check`/`just fix`/`just lint`/`just format` etc.
Why it matters to a newcomer: Not misleading today, but it is two sources of truth for the same four commands; AGENTS.md already carries one detail (the ruff version pin and the `docker/playwright-smoke.py` gotcha) that docs/development.md lacks, so they have already started to drift.
Proposed fix: Wave 4 rewrite should keep the commands in one place (`docs/development.md`) and have AGENTS.md link to it, the way it already does for the four-layer architecture and proxy design.
Proposed PR: docs-newcomer-rewrite (wave 4; see outline below)

### AGENTS.md's "Outbound proxy support" section is a third of the document by word count
Severity: low
Evidence: AGENTS.md:245 `## Outbound proxy support` through AGENTS.md:283 — 1,893 words / 13,576 characters (`sed -n '245,283p' AGENTS.md | wc -w`) against 5,951 words for the whole file — roughly 32%. `wc -l` reports only 38 physical lines because the section is written in long unwrapped paragraphs (one line is 1,603 characters — `awk '{print length, NR}' AGENTS.md | sort -rn | head -1`), which renders as well over 100 lines at a normal terminal width.
Why it matters to a newcomer: AGENTS.md's job is orientation; a newcomer skimming it for "how do I write a test" or "how do PRs get titled" has to scroll past a proxy deep-dive (four "sharp edges," httpx-vs-Chromium NO_PROXY semantics, SOCKS handling) that only matters to someone actively touching `vip/proxy.py`.
Proposed fix: Move the section to a new `docs/proxy.md` (or fold into `docs/development.md`), leaving a two-sentence pointer in AGENTS.md the way the four-layer architecture section already links out to `docs/test-architecture.md`.
Proposed PR: docs-newcomer-rewrite (wave 4; see outline below)

## Proposed PRs

| slug | theme | files | est. changed lines | depends on |
|---|---|---|---|---|
| docs-remove-orphan-root-files | delete two unreferenced root docs | CHRONICLE_TEST_PLAN.md, IMPLEMENTATION_GUIDE.md | ~515 (deletion) | none |
| docs-remove-shipped-plans | delete plans for closed/merged issues | 20 files under thoughts/shared/plans/ (listed above) | large deletion, single theme | none |
| docs-remove-validation-docs | delete showboat transcripts for closed issues | validation_docs/demo-477-positron-console.md, validation_docs/demo-workbench-parallel-484.md | ~60 (deletion) | none |
| docs-remove-orphan-redirect-stubs | delete or index six unlinked docs/ redirect stubs | docs/authentication.md, docs/configuration.md, docs/deployment-verification.md, docs/getting-started.md, docs/test-categories.md, docs/reporting.md | ~30 (deletion) | Ian confirmation (may be intentional bookmark catchers) |
| docs-fix-stale-references | fix commands/paths/features that no longer match the code | examples/custom_tests/README.md, examples/cross_product_validation/README.md, .claude/agents/test-architect.md, presentations/se-overview/index.qmd | <40 | none |
| docs-newcomer-rewrite | wave 4: rewrite AGENTS.md + docs/development.md for newcomers | AGENTS.md, docs/development.md | large (full rewrite) | waves 1-3 (must describe the post-split layout, the `VipError` hierarchy, and the enforced comment policy) |

### Wave 4 outline (docs-newcomer-rewrite)

The rewrite must cover, in addition to whatever waves 1-3 produce:

1. **Comment policy** — state the "1-2 sentences on what/why, no history narration" rule explicitly in AGENTS.md; today it exists only as an unwritten convention this program is enforcing via lint.
2. **Error-handling policy** — once wave 2 lands, document the `VipError` hierarchy, where `except Exception` is still allowed (third-party calls, `# noqa: BLE001`), and that test code never catches `VipError`.
3. **De-duplicate lint/format commands** with docs/development.md — one source of truth, AGENTS.md links to it.
4. **Move or shrink "Outbound proxy support"** (32% of the document) into `docs/`; AGENTS.md keeps a short pointer, matching how it already handles the four-layer architecture.
5. **Fix the docs/ vs website/ split** — either restore real content to the docs/*.md stubs or state plainly (in a `docs/README.md` or in AGENTS.md) that `docs/development.md` and `docs/test-architecture.md` are the only current files and the rest live on the website.
6. **Reflect the post-structure-split layout** (wave 3): update the "Key source files" table for the new `src/vip/auth/`, `src/vip/cli/`, `src/vip/plugin/` packages once they exist, and drop the re-export note once the final pruning PR lands.
7. **Re-verify `.claude/agents/test-architect.md`** against whatever fixture/skip conventions exist after wave 2/3, not just today's two errors.

## Not findings

- `justfile`'s `typecheck` and `coverage` recipes both correctly pass `uv run --extra dev`, and a `test`/`test-product`/`report` recipe check shows they point at the real `src/vip_tests/` directory — a prior session's note claiming these were broken is stale as of this checkout; verified live (`uv run --extra dev mypy --version` succeeds, `grep -n -A3 "^typecheck:\|^coverage:\|^test \|^test-product\|^report " justfile` shows correct paths).
- `README.md`'s CLI command table and container-usage section match `vip --help` / `vip status --help` / `vip verify --help` exactly, including `--ci`, `--format`, exit code 6, and `vip status --json`.
- `docs/test-architecture.md`'s `VIP_TIMEOUT_SCALE`, `--extensions`, and `vip scaffold` examples all match current code and `--help` output.
- `AGENTS.md` already documents the two-suite (selftests vs. product tests) distinction clearly and correctly.
- `.claude/settings.json` and `.claude/scripts/setup-gh.sh` are internal Claude Code tooling, self-contained and not meant for a human newcomer; they work as wired (referenced correctly by the hook config) and need no separate documentation.
- `.claude/agents/weekly-summary.md` matches the current `weekly-summary.yml` workflow and PR-title conventions; no staleness found.
- `presentations/qa-overview/index.qmd`'s Chronicle/`min_version` example (Connect 2026.06.0) is current and consistent with `src/vip/version.py`.
- CHANGELOG.md, examples/_shared/AGENTS.md, and the two example READMEs' non-`--collect-only` commands are accurate against current `vip scaffold --list` output.
