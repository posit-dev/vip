# VIP Quality Program, Phase 1 and 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce eight evidence-backed review documents, merge them into one PR backlog partitioned into conflict-free waves, and hand Ian the wave 1 approval package.

**Architecture:** Eight read-only Sonnet 5 reviewer agents run concurrently against this worktree, each writing one findings file under `thoughts/shared/reviews/`. The coordinator then merges findings into `thoughts/shared/plans/2026-09-14-quality-program-backlog.md`, verifies wave disjointness with a script, and records everything in a continuity ledger. Waves 1 to 4 each get their own implementation plan afterwards, generated from the backlog.

**Tech Stack:** Python 3.10+, uv 0.11.28, ruff 0.15.0, mypy, pytest, pytest-bdd, Playwright, Typer, GitHub CLI.

**Spec:** `thoughts/shared/plans/2026-09-14-quality-program-design.md`

## Global Constraints

- Reviewers are read-only. They create exactly one file each under `thoughts/shared/reviews/` and change nothing else.
- Every finding has an `Evidence:` line with at least one `path:line` and a quoted source line. Findings without evidence are deleted at merge time.
- Worktree for all phase 1 and 2 work: `/Users/ianfloressiaca/ptd-workspace/.worktrees/vip-quality-program`, branch `quality-program-design`, based on `origin/main` at `ff81793d`.
- All Python commands go through `uv run`. Mypy needs the dev extra: `uv run --extra dev mypy`.
- Branch names are kebab-case, contain no `/`, and contain no personal names.
- Commit messages and PR text require Ian's approval. Phase 1 and 2 produce documents only; the single commit at the end of phase 2 is proposed to Ian, not executed without a yes.
- Baselines measured on `ff81793d` on 2026-09-14: selftests `1951 passed, 3 skipped`; `mypy src/vip` clean; `mypy src/vip src/vip_tests` 6 errors in 5 files; `mypy selftests` 8 errors in 4 files; `mypy --strict src/vip` 119 errors in 18 files.
- Ruff family violation counts on the same commit (`--select <family>` over `src/ selftests/ examples/ docker/`): B 7, BLE 121, C4 2, SIM 80, RUF 40, PL 1075, D 2518, N 3, ARG 463, RET 9, PTH 16, T20 125, ERA 11, S 3137.

---

## Shared reviewer prompt

Every reviewer task in phase 1 dispatches an agent with `subagent_type: "general-purpose"`, `model: "sonnet"`, and this prompt with the three placeholders filled in. The placeholders are `<LENS>`, `<SCOPE>`, and `<LENS QUESTIONS AND COMMANDS>`; each task below supplies exact values.

````
You are a code reviewer for the VIP repository (posit-dev/vip), a pytest-bdd test suite that validates Posit Team installations. You are one of eight reviewers running in parallel. Your lens is: <LENS>.

Working directory: /Users/ianfloressiaca/ptd-workspace/.worktrees/vip-quality-program
This is a git worktree at origin/main. Run every command from this directory. Do not cd elsewhere, do not create branches, do not edit or create any file except your output file.

Read first, in this order:
1. thoughts/shared/plans/2026-09-14-quality-program-design.md (the program you are feeding; pay attention to "Decisions already made", "Error handling design", "Structure design", and "Out of scope")
2. AGENTS.md (the repo's own conventions; a finding that contradicts a documented convention must say so and argue why the convention should change, or be dropped)

Your scope: <SCOPE>

Your questions and the commands to answer them:
<LENS QUESTIONS AND COMMANDS>

Output: write exactly one file, thoughts/shared/reviews/2026-09-14-<LENS>.md, with this structure:

# Review: <LENS>

## Summary
Three to six sentences. What is the overall state in this lens, and what are the two or three findings that matter most for a newcomer to the codebase.

## Findings
Ordered by severity, high first. Every finding uses exactly this shape:

### <short title, imperative, under 70 chars>
Severity: high | medium | low
Evidence: <path>:<line> `<quoted source line>` (repeat the Evidence line for each additional location; for mechanical findings with more than ten sites, give five representative locations and the exact command that lists all of them)
Why it matters to a newcomer: <one or two sentences>
Proposed fix: <one or two sentences, concrete>
Proposed PR: <kebab-case-slug> (files: <comma-separated list of every file the fix touches>)

## Proposed PRs
A table with columns: slug | theme | files | estimated changed lines | depends on. Several findings may share a slug when they are one theme and one file set. A PR should stay under about 400 changed lines unless it is a single mechanical ruff rule family.

## Not findings
Things you checked that turned out fine or are deliberate. One line each. This stops the next reviewer from re-raising them.

Rules:
- Severity high means a newcomer will be misled or a real failure is hidden. Medium means friction. Low means polish.
- Never propose a fix without evidence. Never guess at line numbers; run the command and copy the output.
- Do not propose changes listed under "Out of scope" in the design doc.
- Do not restate the design doc's own examples as findings unless you add new evidence.
- You have no budget for reading the whole repository line by line. Use grep, ruff, mypy, git log, and targeted reads. Aim for depth on the ten to twenty findings that matter, not breadth.
- When you finish, reply with only: the output path, the count of findings by severity, and the list of proposed PR slugs.
````

---

## Phase 1: parallel reviews

### Task 1: Create the continuity ledger

**Files:**
- Create: `thoughts/ledgers/CONTINUITY_CLAUDE-vip-quality-program.md`

**Interfaces:**
- Produces: the ledger every later task updates. Phase and wave markers use `[x]`, `[→]`, `[ ]`.

- [ ] **Step 1: Write the ledger**

```markdown
# Continuity Ledger: vip-quality-program

## Goal
Bring posit-dev/vip to newcomer-readable, typed-error, CI-enforced quality via many small draft PRs. Done when every item in the design doc's "Done means" list holds. Design: thoughts/shared/plans/2026-09-14-quality-program-design.md.

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

## State
- Done:
  - [x] Design spec committed (dbbdfb32)
- Now: [→] Phase 1: eight parallel reviews
- Next: Phase 2: merge backlog, partition waves, wave 1 approval package
- Remaining:
  - [ ] Phase 1 reviews: comments, error-handling, structure, typing-lint, selftests, product-tests, docs-hygiene, ci-tooling
  - [ ] Phase 2: backlog merged and disjointness verified
  - [ ] Wave 1 approved by Ian
  - [ ] Wave 1 PRs open and reviewed
  - [ ] Wave 2 approved / open / reviewed
  - [ ] Wave 3 approved / open / live-gated / reviewed
  - [ ] Wave 4 approved / open / reviewed

## Open Questions
- UNCONFIRMED: does wave 3 wait for #627 to merge, or build on its branch?

## Working Set
- Worktree: ~/ptd-workspace/.worktrees/vip-quality-program (branch quality-program-design)
- Reviews: thoughts/shared/reviews/2026-09-14-*.md
- Backlog: thoughts/shared/plans/2026-09-14-quality-program-backlog.md
- Baseline: selftests 1951 passed / 3 skipped on ff81793d
- Test commands: `just check`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, `uv run pytest src/vip_tests/ --collect-only --quiet`
```

- [ ] **Step 2: Verify**

Run: `test -f thoughts/ledgers/CONTINUITY_CLAUDE-vip-quality-program.md && grep -c '\[→\]' thoughts/ledgers/CONTINUITY_CLAUDE-vip-quality-program.md`
Expected: `1`

### Task 2: Dispatch all eight reviewers concurrently

All eight `Agent` calls go in one message so they run in parallel. Each uses the shared reviewer prompt with the values below.

**Files:**
- Create (by agents): `thoughts/shared/reviews/2026-09-14-{comments,error-handling,structure,typing-lint,selftests,product-tests,docs-hygiene,ci-tooling}.md`

**Interfaces:**
- Produces: eight review files in the shared finding format. Task 3 parses the `Proposed PR:` lines and the `## Proposed PRs` tables.

- [ ] **Step 1: Dispatch reviewer `comments`**

LENS: `comments`
SCOPE: `src/, selftests/, examples/, docker/`
LENS QUESTIONS AND COMMANDS:
```
1. Which comments and docstrings narrate change history instead of describing current behavior? Start from:
   git grep -n -i -E '(previously|used to|no longer|was (moved|removed|renamed|added)|formerly|before this change|historically|legacy|see (issue|PR) ?#?[0-9]+|fixes? #[0-9]+|issue #[0-9]+|\(#[0-9]+\))' -- 'src/**/*.py' 'selftests/**/*.py' 'examples/**/*.py' 'docker/*.py'
   Classify each hit: (a) pure history, delete; (b) history plus a still-true rationale, rewrite to the rationale; (c) needed link to an issue for a workaround that must be revisited, keep. Report counts per class and per module.
2. Which comments are wrong about the code beneath them? Sample the 20 longest comment blocks (find them with: git grep -n -E '^\s*#' -- 'src/**/*.py' | awk -F: '{print $1}' | sort | uniq -c | sort -rn | head) and read the code they describe.
3. Where are docstrings missing on public functions whose name does not make the contract obvious? Use: uv run ruff check --select D103,D102 --statistics --exit-zero src/vip
4. Which comments exceed five lines? Those are candidates for a docstring, a named helper, or deletion. Use: awk with a running count of consecutive '#' lines over src/vip/*.py.
Propose PRs per module (for example comments-auth, comments-cli, comments-plugin, comments-tests-workbench) so each stays reviewable.
```

- [ ] **Step 2: Dispatch reviewer `error-handling`**

LENS: `error-handling`
SCOPE: `src/vip, src/vip_tests`
LENS QUESTIONS AND COMMANDS:
```
1. Enumerate every broad except: uv run ruff check --select BLE001 --output-format concise --exit-zero src/ | sort
   For each of the 121 sites, classify: (a) swallows and continues silently; (b) logs and continues; (c) converts to pytest.skip or a soft result; (d) re-raises or wraps; (e) genuinely tolerating an unknown third-party failure. Report counts per class and list every class (a) and (c) site individually, they are the high-severity ones.
2. Where do exit paths bypass the reporter or the single CLI handler the design doc calls for? git grep -n -E 'sys\.exit|typer\.Exit|raise SystemExit|os\._exit' -- 'src/**/*.py'
3. Where is a Playwright TimeoutError or httpx error caught by a broad type when the concrete type is known? git grep -n -B3 'except Exception' -- 'src/vip/auth.py' 'src/vip/workbench_ui.py' 'src/vip/clients/*.py' and read each block.
4. Which functions return None or a sentinel on failure where a raised error would be clearer? Look for 'return None' and 'return False' directly inside except blocks.
5. Map the existing failure vocabulary: what messages do users actually see (grep for 'Error:', 'FAILED', '>>>', 'Hint:' in src/vip). Which of those map to which VipError subclass in the design doc? Flag any failure class the design's hierarchy does not cover.
Propose one PR for the hierarchy itself (src/vip/errors.py plus the cli.py handler plus selftests), then one PR per module for narrowing, in the order auth.py, clients/, proxy.py, install/, plugin.py, workbench_ui.py, vip_tests/workbench.
```

- [ ] **Step 3: Dispatch reviewer `structure`**

LENS: `structure`
SCOPE: `src/vip, src/vip_tests/**/conftest.py`
LENS QUESTIONS AND COMMANDS:
```
1. For each of auth.py, cli.py, plugin.py, and src/vip_tests/workbench/conftest.py: list every top-level def and class with its line range and which other top-level names in the same file it calls. Use: uv run ruff check --select PLR0915,PLR0912,PLR0913,C901 --output-format concise --exit-zero <file> for complexity hot spots, and grep -n '^def \|^class \|^async def ' <file> for the inventory. From the call graph propose the seam: which functions form a cohesive cluster that becomes one module. Compare against the design doc's proposed layout and say where it is wrong.
2. Which private helpers are called from exactly one place in another module? Those belong next to their caller. For each name matching ^def _ in src/vip/*.py, grep for uses outside the defining file.
3. Import cycles and layering: grep -n '^from vip\|^import vip\|^    from vip' src/vip/*.py src/vip/**/*.py and draw the module dependency graph. Flag any import inside a function body that exists only to break a cycle.
4. Duplicated fixtures: grep -n '^def \|^@pytest.fixture' across src/vip_tests/**/conftest.py and src/vip/fixtures.py; list fixtures defined more than once or with near-identical bodies.
5. Public surface: what does each module export that is used outside src/vip? grep imports from src/vip_tests and selftests. This defines what the __init__.py re-exports must preserve in a split.
Propose one PR per split (structure-auth-package, structure-cli-package, structure-plugin-package, structure-workbench-conftest) with the exact target module list and which functions move where. Also propose any pre-split PRs that make a split safer, such as moving a stray helper first.
```

- [ ] **Step 4: Dispatch reviewer `typing-lint`**

LENS: `typing-lint`
SCOPE: whole Python tree: `src/, selftests/, examples/, docker/`
LENS QUESTIONS AND COMMANDS:
```
1. For each ruff family in this list run: uv run ruff check --select <FAM> --statistics --exit-zero src/ selftests/ examples/ docker/
   Families: B, BLE, C4, SIM, RUF, PL, D, N, ARG, RET, PTH, T20, ERA, S, PIE, PERF, FBT, TRY, EM, ISC, PGH, TID, PT.
   Baseline counts already known: B 7, BLE 121, C4 2, SIM 80, RUF 40, PL 1075, D 2518, N 3, ARG 463, RET 9, PTH 16, T20 125, ERA 11, S 3137. For every family recommend one of: enable whole (fix count is small and every fix is an improvement), enable with a short list of per-rule ignores (name the rules and why), or do not enable (say why). For PL, D, and S recommend the specific rule subset worth enabling; for example S is dominated by S101 assert-in-tests which is correct in a test suite. Check whether T20 hits are legitimate CLI output (the CLI uses typer.echo or rich? verify) or stray debug prints.
2. Mypy scope and strictness. Known: mypy src/vip is clean; adding src/vip_tests gives 6 errors in 5 files; selftests gives 8 errors in 4 files; --strict on src/vip gives 119 errors in 18 files. Run each and list every error. Recommend which strict flags to adopt now (candidates: disallow_untyped_defs, warn_return_any, warn_unused_ignores, no_implicit_optional, check_untyped_defs) with the error count each adds. List all 21 'type: ignore' comments (grep -rn 'type: ignore' src selftests) and which have no error code.
3. Are the ruff and mypy configurations consistent between pyproject.toml, .pre-commit-config.yaml, justfile, and .github/workflows/ci.yml? Quote each pin and each path list.
4. Python version floor: pyproject says python_version 3.10 for mypy and UP rules. Confirm requires-python and whether any 3.11+ syntax already slipped in.
Propose one PR per family or per mypy flag group, each named lint-<family> or typing-<flag>, with the exact pyproject.toml diff and the violation count it fixes. Order them cheapest first.
```

- [ ] **Step 5: Dispatch reviewer `selftests`**

LENS: `selftests`
SCOPE: `selftests/`
LENS QUESTIONS AND COMMANDS:
```
1. Which selftest files are too large to navigate? wc -l selftests/*.py | sort -rn | head -15. For every file over 800 lines, list the test classes or the natural subject groups (by fixture use and by the src/vip function under test) and propose a split into files under about 500 lines each.
2. Which tests share a source of truth with the code under test? Look for tests that import a constant, template, or message string from src/vip and assert equality against it: git grep -n -E 'from vip[.a-z_]* import .*(_TEMPLATE|_FILES|_MESSAGE|_TEXT|_PATTERN|_URL|DEFAULT_)' -- selftests/. A test that asserts `x == vip.module.CONST` pins nothing. Each is a finding.
3. Where is pytester (subprocess pytest) used when a direct function call would test the same behavior faster? grep -n 'pytester' selftests/*.py | awk -F: '{print $1}' | uniq -c. Read three of the heavier users and judge.
4. Duplicated fixtures and helpers across selftest files: grep -n '^def \|^@pytest.fixture' selftests/*.py selftests/conftest.py and list names defined in more than one file.
5. Mocking depth: where do tests mock so much of Playwright or httpx that they only test the mock? Sample selftests/test_auth.py; report how many tests would still pass if the function under test returned early.
6. Slow tests: uv run pytest selftests/ --durations=15 -q -p no:cacheprovider 2>&1 | tail -25. Anything over two seconds is a finding with a reason.
Propose PRs per file split (selftests-split-auth, selftests-split-plugin, ...) and one PR for de-duplicating fixtures into selftests/conftest.py.
```

- [ ] **Step 6: Dispatch reviewer `product-tests`**

LENS: `product-tests`
SCOPE: `src/vip_tests/`
LENS QUESTIONS AND COMMANDS:
```
1. Convention drift across the seven categories (prerequisites, package_manager, connect, workbench, cross_product, performance, security). For each, record: how steps are named (grep -n '@given\|@when\|@then' and compare phrasing patterns); how skips are expressed (pytest.skip vs the if_applicable marker vs returning early); how timeouts are set (literal ms vs vip.timeouts constants: git grep -n -E 'timeout=[0-9]{3,}' -- src/vip_tests); how selectors are written (CSS vs role-based vs text: git grep -n -E "locator\(|get_by_role\(|get_by_text\(" -- src/vip_tests | awk -F: '{print $1}' | sort | uniq -c). Findings are the outliers, with the majority convention named as the target.
2. Feature file and step drift: for each .feature file, do all steps have a matching step definition and are there step definitions with no feature using them? Use: uv run pytest src/vip_tests/ --collect-only -q 2>&1 | tail -5 for collection health, then grep step text against @given/@when/@then decorators for a sample of five features.
3. Unguarded Playwright calls: .fill(), .click(), .type() without a preceding visibility or editability wait and without an explicit timeout. git grep -n -E '\.(fill|click|type)\(' -- src/vip_tests | wc -l, then sample twenty and classify.
4. Test-side broad excepts and soft failures: uv run ruff check --select BLE001 --output-format concise --exit-zero src/vip_tests. A product test that catches Exception and skips or passes is a high finding.
5. Fixture placement: which fixtures live in a category conftest but are used by another category? Which live in src/vip/fixtures.py but are used by one category only?
Do NOT propose behavior changes to tests, new tests, or flake fixes; those are out of scope. Propose PRs that align conventions mechanically (for example product-tests-timeout-constants, product-tests-skip-style) and PRs that fix findings from question 4.
```

- [ ] **Step 7: Dispatch reviewer `docs-hygiene`**

LENS: `docs-hygiene`
SCOPE: root `*.md`, `docs/`, `thoughts/`, `validation_docs/`, `presentations/`, `website/`, `examples/*/README.md`, `.claude/`
LENS QUESTIONS AND COMMANDS:
```
1. Orphans: for every markdown file outside website/, is it linked from README.md, docs/, AGENTS.md, or the website? git ls-files '*.md' | while read f; do n=$(git grep -l "$(basename $f)" -- . ':!'"$f" | wc -l); echo "$n $f"; done | sort -n. Known orphans: CHRONICLE_TEST_PLAN.md and IMPLEMENTATION_GUIDE.md.
2. Shipped plans: for each file in thoughts/shared/plans/ whose name contains issue-NNN, run gh issue view NNN -R posit-dev/vip --json state,title -q '"\(.state) \(.title)"'. Every CLOSED one is a deletion candidate. For plans without an issue number, check git log for the PR that implemented them. Also check validation_docs/ and presentations/ the same way. Do not list the two 2026-09-14-quality-program-* files; they are live.
3. Duplication and staleness in docs/: which sections repeat across docs/*.md and AGENTS.md? Which describe commands, flags, or file paths that no longer exist (verify each `vip` subcommand and just recipe mentioned against `uv run vip --help` and `just --list`)?
4. Newcomer path: read README.md then docs/getting-started.md then docs/development.md as a newcomer would. Where does the path break: a missing prerequisite, an unexplained term, a command that fails? Try the commands.
5. AGENTS.md: which rules are stale relative to the code, and which rules a newcomer needs are missing (for example the two-suite distinction is there; is the error-handling policy? the comment policy?). Do not rewrite it; the design doc schedules the rewrite for wave 4. Report what the rewrite must cover.
6. .claude/ contents shipped in the repo: agents and scripts. Are they documented, and do they still work?
Propose PRs: docs-remove-orphan-root-files, docs-remove-shipped-plans (one PR, list every file with its closed issue), docs-remove-validation-docs, docs-fix-stale-references, and a wave 4 entry docs-newcomer-rewrite with the outline the rewrite must follow.
```

- [ ] **Step 8: Dispatch reviewer `ci-tooling`**

LENS: `ci-tooling`
SCOPE: `.github/`, `justfile`, `pyproject.toml`, `Dockerfile`, `compose.yml`, `compose.mock-idp.yml`, `.pre-commit-config.yaml`, `.dockerignore`, `cliff.toml`, `uv.lock`
LENS QUESTIONS AND COMMANDS:
```
1. Local versus CI parity. Build a table: every check ci.yml runs (job name, exact command) and the just recipe or pre-commit hook that runs the same thing locally. Flag checks that exist in only one place. Known: mypy in CI is `uv run mypy src/vip/` while the justfile uses `uv run --extra dev mypy src/vip/`; verify which works from a clean `uv sync`. Known: `just coverage` and `just typecheck` have a history of failing after plain `just setup` (see git log -S 'extra dev' -- justfile).
2. Pins: list every version pin of uv, ruff, Python, actions (uses: with @sha or @tag), Playwright, Quarto across all files in scope. Flag inconsistencies and unpinned actions. Run: grep -rn 'uses:' .github/workflows | grep -v '@[0-9a-f]\{40\}' for unpinned or tag-pinned actions.
3. The 21 workflows: for each, one line on trigger, purpose, and whether it ran successfully in the last 30 days (gh run list -R posit-dev/vip --workflow <file> --limit 5 --json conclusion,createdAt). Flag workflows that have not run, always fail, or duplicate another.
4. justfile: run `just --list` and `just --evaluate`; for each recipe, does it run on a fresh clone? Try `just check`, `just typecheck`, `just selftest -x -q`. Recipes that fail or are undocumented in docs/development.md are findings.
5. Packaging: does `uv build` succeed and does the wheel contain the force-included scaffold and report assets listed in pyproject? Run: uv build 2>&1 | tail -3 && unzip -l dist/*.whl | grep -E '_scaffold|_report' | wc -l.
6. Pre-commit: which hooks exist versus which CI checks exist. Is pre-commit installation documented?
Propose PRs: ci-local-parity (justfile changes), ci-pin-actions, ci-remove-dead-workflows (only if evidence supports), tooling-precommit-parity, each with the exact file diff sketched.
```

- [ ] **Step 9: Wait for all eight, then verify outputs**

Run:
```bash
ls thoughts/shared/reviews/2026-09-14-*.md | wc -l
for f in thoughts/shared/reviews/2026-09-14-*.md; do
  echo "== $f: findings=$(grep -c '^### ' "$f") evidence=$(grep -c '^Evidence:' "$f") prs=$(grep -c '^Proposed PR:' "$f")"
done
git status --short | grep -v '^?? thoughts/shared/reviews/' || echo "clean apart from reviews"
```
Expected: `8` files; for every file `evidence >= findings` and `prs == findings`; the git status line prints `clean apart from reviews`. If any reviewer edited anything else, `git checkout` is forbidden by Ian's rules; instead run `git diff --stat` and hand the diff back to that reviewer via SendMessage to revert its own edits.

- [ ] **Step 10: Update ledger**

Mark the Phase 1 review checkbox `[x]`, move `[→]` to Phase 2.

---

## Phase 2: backlog and waves

### Task 3: Merge the eight reviews into one backlog

**Files:**
- Create: `thoughts/shared/plans/2026-09-14-quality-program-backlog.md`
- Read: all eight review files

**Interfaces:**
- Consumes: `### <title>` findings with `Proposed PR: <slug> (files: ...)` lines.
- Produces: a backlog where every PR entry has `slug`, `wave`, `theme`, `files`, `findings` (list of `review-file#title` references), `approval status`, `PR number`, `state`.

- [ ] **Step 1: Extract every proposed PR into a working table**

Run:
```bash
grep -H '^Proposed PR:' thoughts/shared/reviews/2026-09-14-*.md \
  | sed -E 's#thoughts/shared/reviews/2026-09-14-([a-z-]+)\.md:Proposed PR: ([a-z0-9-]+) \(files: (.*)\)#\1|\2|\3#' \
  | sort -t'|' -k2 > /private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/prs.psv
wc -l /private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/prs.psv
cut -d'|' -f2 /private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/prs.psv | sort | uniq -c | sort -rn | head -20
```
Expected: one row per finding; the uniq count shows slugs proposed by more than one lens, which are the merge candidates.

- [ ] **Step 2: Dedupe and reject**

For each slug proposed by two or more lenses, keep one entry and list all contributing findings. Delete any finding whose `Evidence:` line fails `grep -n` against the quoted source in the file it names. Delete any finding that targets an "Out of scope" item from the design doc. Record every deletion in a `## Rejected` section of the backlog with a one-line reason.

- [ ] **Step 3: Assign waves and write the backlog**

Wave rules from the design doc: wave 1 hygiene and ratchet; wave 2 error handling; wave 3 structure and selftest splits; wave 4 docs rewrite. Within a wave, two PRs may not share a file. If they do, either merge them into one PR (if same theme) or move the later one to the next wave and note `depends on: <slug>`.

Backlog format:

```markdown
# VIP quality program backlog

Generated 2026-09-14 from thoughts/shared/reviews/2026-09-14-*.md. Design: 2026-09-14-quality-program-design.md.

## Wave 1: hygiene and ratchet
| # | slug | theme | files | findings | depends on | approval | PR | state |
|---|------|-------|-------|----------|------------|----------|----|-------|
| 1.1 | docs-remove-orphan-root-files | docs | CHRONICLE_TEST_PLAN.md, IMPLEMENTATION_GUIDE.md | docs-hygiene#Orphan root docs | | pending | | planned |

## Wave 2: error handling
...

## Wave 3: structure
...

## Wave 4: docs rewrite
...

## Rejected
- <review>#<title>: <reason>

## #627 collision list
PRs whose file set intersects PR #627: <slugs>. Decision pending from Ian.
```

- [ ] **Step 4: Verify wave disjointness with a script**

Create `/private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/check_waves.py`:

```python
"""Fail if two PRs in the same wave touch the same file."""
import re
import sys
from collections import defaultdict
from pathlib import Path

backlog = Path(sys.argv[1]).read_text()
wave = None
seen: dict[str, dict[str, str]] = defaultdict(dict)
bad = 0
for line in backlog.splitlines():
    m = re.match(r"^## Wave (\d)", line)
    if m:
        wave = m.group(1)
        continue
    if wave and line.startswith("| ") and not line.startswith("| #") and not line.startswith("|---"):
        cells = [c.strip() for c in line.strip("|").split("|")]
        slug, files = cells[1], cells[3]
        for f in [x.strip() for x in files.split(",") if x.strip()]:
            if f in seen[wave] and seen[wave][f] != slug:
                print(f"wave {wave}: {f} in both {seen[wave][f]} and {slug}")
                bad += 1
            seen[wave][f] = slug
print("OK" if bad == 0 else f"{bad} collisions")
sys.exit(1 if bad else 0)
```

Run: `uv run python /private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/check_waves.py thoughts/shared/plans/2026-09-14-quality-program-backlog.md`
Expected: `OK`

- [ ] **Step 5: Verify #627 collision list**

Run:
```bash
gh pr view 627 -R posit-dev/vip --json files -q '.files[].path' | sort > /private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/pr627.txt
grep -oE '\| [0-9]\.[0-9]+ \| [a-z0-9-]+ \| [a-z-]+ \| [^|]+' thoughts/shared/plans/2026-09-14-quality-program-backlog.md \
  | while IFS='|' read -r _ num slug theme files; do
      for f in $(echo "$files" | tr ',' ' '); do grep -qx "$f" /private/tmp/claude-501/-Users-ianfloressiaca/93ed1824-63c4-4825-b61f-b8c7a7182f6b/scratchpad/pr627.txt && echo "$slug collides on $f"; done
    done | sort -u
```
Expected: the printed slugs equal the backlog's `#627 collision list` section.

- [ ] **Step 6: Update ledger**

Mark Phase 2 `[x]`, move `[→]` to "Wave 1 approved by Ian". Add the backlog path and the collision list to Working Set.

### Task 4: Wave 1 approval package for Ian

**Files:**
- Create: `thoughts/shared/plans/2026-09-14-wave1-approval.md`

**Interfaces:**
- Consumes: wave 1 rows of the backlog.
- Produces: the exact PR title and body text implementers will use verbatim once Ian approves.

- [ ] **Step 1: Write one entry per wave 1 PR**

Format for each:

```markdown
## 1.N <slug>
Branch: <slug>
Title: <type>(<scope>): <imperative summary under 70 chars>
Body:
<one paragraph on a single line: what changes and why a newcomer benefits. No hard wraps.>

<second paragraph, single line: how it was verified, naming the exact commands.>

Files: <list>
Findings: <review#title list>
```

Title types follow the repo's existing conventional-commit usage (`fix`, `feat`, `docs`, `chore`, `refactor`, `test`, `ci`), enforced by `.github/workflows/pr-title.yml`; read that file and copy its allowed type list into the top of the approval doc.

- [ ] **Step 2: Verify titles against the PR title workflow**

Run: `grep -A20 'types:' .github/workflows/pr-title.yml | head -25` and check every proposed title's type appears in that list and every title is under 70 characters:
```bash
grep '^Title:' thoughts/shared/plans/2026-09-14-wave1-approval.md | awk '{ $1=""; l=length($0)-1; if (l>70) print "TOO LONG", l, $0 }'
```
Expected: no output.

- [ ] **Step 3: Propose the phase 2 commit to Ian**

Do not commit. Present this message for approval alongside the approval package:

```
docs(plans): add quality program reviews, backlog, and wave 1 approval package
```

Files to stage on approval: `thoughts/shared/reviews/2026-09-14-*.md`, `thoughts/shared/plans/2026-09-14-quality-program-backlog.md`, `thoughts/shared/plans/2026-09-14-wave1-approval.md`, `thoughts/shared/plans/2026-09-14-quality-program-phase1-plan.md`, `thoughts/ledgers/CONTINUITY_CLAUDE-vip-quality-program.md`.

- [ ] **Step 4: Report to Ian**

One message: count of findings by severity per lens, count of PRs per wave, the #627 collision list, the wave 1 approval package summarized as a table of slug and title, and the pending commit message. Stop and wait for approval. Wave 1 implementation begins only after Ian's yes, under its own plan generated from the backlog.
