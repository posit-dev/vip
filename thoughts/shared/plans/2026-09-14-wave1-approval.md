# VIP quality program: wave 1 approval package

For Ian's batch approval per the design doc ("Approvals: Batch per wave. Ian approves the full list of PR titles and bodies once per wave. Agents use that text verbatim."). Covers wave 1a (18 PRs) and wave 1b (15 PRs) from `thoughts/shared/plans/2026-09-14-quality-program-backlog.md`, 33 PRs total, in backlog order.

## PR title rules

Copied from `.github/workflows/pr-title.yml`, which `amannn/action-semantic-pull-request` enforces on every PR:

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.

- Format: `<type>: <description>` or `<type>(<scope>): <description>`. Scope is optional (`requireScope: false`).
- The subject after the type must not be empty (`subjectPattern: ^.+$`).
- A `!` after the type or scope marks a breaking change (e.g. `feat!: ...`) — not used anywhere in this wave.

Additional rules from AGENTS.md's "PR titles" section, not enforced by the workflow but required by repo convention:

- Do not capitalize the first letter of the description.
- Do not end the description with a period.
- Keep the title under 70 characters.

## 1.1 comments-cli

Branch: comments-cli
Title: docs(cli): rewrite history comments to state current behavior
Body:
Strips comment sentences in cli.py that narrate what the code "used to" do and rewrites the longer "used to/previously" rationale blocks to lead with the invariant they justify, per the comments review's findings on cli.py's history narration and rationale framing; a newcomer reading cli.py should see why the code works the way it does today, not a changelog of how it got there.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; comment-only change, no test behavior affected.

Files: src/vip/cli.py
Findings: comments#A handful of comments are pure history with no surviving rationale; comments#Long "used to / previously" rationale comments in the three god-modules mix real invariants with change-history framing
Depends on: rebases trivially if #627 or #658 lands first (comment-only edit; both touch src/vip/cli.py)

## 1.2 comments-fixtures-proxy-plugin

Branch: comments-fixtures-proxy-plugin
Title: docs(fixtures): add fixture docstrings and rewrite rationale comments
Body:
Adds docstrings to the connect_client/workbench_client/pm_client fixtures stating their None-when-unconfigured and cookie-injection contracts, and rewrites the long "used to/previously" rationale comments in fixtures.py, proxy.py, and plugin.py to lead with the invariant instead of the change history, per the comments review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; comment/docstring-only change.

Files: src/vip/fixtures.py, src/vip/proxy.py, src/vip/plugin.py
Findings: comments#`connect_client`, `workbench_client`, `pm_client` fixtures have inline comments but no docstring; comments#Long "used to / previously" rationale comments in the three god-modules mix real invariants with change-history framing
Depends on: rebases trivially if #627 lands first (comment-only edit; #627 also touches src/vip/plugin.py)

## 1.3 comments-rationale-auth

Branch: comments-rationale-auth
Title: docs(auth): rewrite rationale comments to lead with the invariant
Body:
Rewrites the long "used to/previously" rationale comments in auth.py — covering the shared SSO timeout, the OIDC/SAML timeout-error wording, and the networkidle wait change — so each leads with the invariant it protects rather than the history of how the code got there, per the comments review's finding on the three god-modules.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; comment-only change.

Files: src/vip/auth.py
Findings: comments#Long "used to / previously" rationale comments in the three god-modules mix real invariants with change-history framing
Depends on: none

## 1.4 comments-strip-history-other

Branch: comments-strip-history-other
Title: docs: delete history-narration comments with no surviving rationale
Body:
Deletes the "used to live in this file"/"previously measured"/loop-hoisting-history sentences in src/vip_tests/conftest.py, cross_product/test_resources.py, and report_content.py that describe a past state a newcomer can never observe, keeping only the sentence that describes current behavior, per the comments review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; comment-only change.

Files: src/vip_tests/conftest.py, src/vip_tests/cross_product/test_resources.py, src/vip/report_content.py
Findings: comments#A handful of comments are pure history with no surviving rationale
Depends on: rebases trivially if #627 lands first (comment-only edit; #627 also touches src/vip/report_content.py)

## 1.5 docstrings-install

Branch: docstrings-install
Title: docs(install): add docstrings to plan, manifest, and runner functions
Body:
Adds docstrings to install/plan.py's build_install_plan/build_uninstall_plan, install/manifest.py's load/save, and install/runner.py's execute_uninstall_plan stating the return/raise contract and side effects each already has but nowhere documents at the definition site, per the comments review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; docstring-only change.

Files: src/vip/install/plan.py, src/vip/install/manifest.py, src/vip/install/runner.py
Findings: comments#`install/plan.py` builders and `install/manifest.py` load/save carry no docstring despite a real, non-obvious contract; comments#`execute_uninstall_plan` has no docstring despite swallowing a callback failure
Depends on: rebases trivially if #659 lands first (docstring-only edit; #659 also touches src/vip/install/runner.py)

## 1.6 docstrings-config

Branch: docstrings-config
Title: docs(config): document the shared from_dict parsing convention
Body:
Adds one docstring stating the shared parsing convention (tolerant of missing keys via dataclass defaults, silent on unknown keys) that all seven from_dict classmethods in config.py already follow but nowhere state, per the comments review, so a contributor adding a new vip.toml key knows the contract without reading all seven implementations.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; docstring-only change.

Files: src/vip/config.py
Findings: comments#Seven `from_dict` classmethods in `config.py` share one undocumented parsing contract
Depends on: none

## 1.7 docs-remove-orphan-root-files

Branch: docs-remove-orphan-root-files
Title: docs: delete orphaned root planning documents
Body:
Deletes CHRONICLE_TEST_PLAN.md, a scratch document that says in its own first line it should never have been committed, and IMPLEMENTATION_GUIDE.md, an orphaned planning doc that open PR #661 replaces with a short redirect stub before this PR lands, per the docs-hygiene review; both sit at the repo root next to README.md and AGENTS.md and read as current onboarding material even though neither is.

Verified with `uv run pytest selftests/ -v` and `uv run pytest src/vip_tests/ --collect-only -q` to confirm no import or doc-link references either file; history is preserved in git.

Files: CHRONICLE_TEST_PLAN.md, IMPLEMENTATION_GUIDE.md
Findings: docs-hygiene#Two root markdown files are orphaned and one says it shouldn't be committed
Depends on: #661 merge

## 1.8 docs-remove-shipped-plans

Branch: docs-remove-shipped-plans
Title: docs: delete implementation plans for closed and merged issues
Body:
Deletes twenty implementation plans under thoughts/shared/plans/ that each target an issue already closed or a PR already merged, per the docs-hygiene review, so a newcomer opening that directory sees only the two plans that belong to the still-active quality program instead of twenty finished ones with no marker distinguishing them.

Verified with `uv run pytest selftests/ -v` to confirm nothing in the test suite reads these plan files; history is preserved in git.

Files: thoughts/shared/plans/2026-05-29-issue-298-custom-test-scaffolding.md, thoughts/shared/plans/2026-05-29-issue-301-workbench-in-session-execution.md, thoughts/shared/plans/2026-05-29-issue-302-workbench-jobs.md, thoughts/shared/plans/2026-05-29-issue-303-workbench-runtime-versions.md, thoughts/shared/plans/2026-05-29-issue-304-k8s-autoscaling-probes.md, thoughts/shared/plans/2026-05-29-issue-305-workbench-idle-session-auto-suspend.md, thoughts/shared/plans/2026-05-29-issue-306-workbench-git-ops.md, thoughts/shared/plans/2026-05-29-issue-307-workbench-to-connect-publishing.md, thoughts/shared/plans/2026-05-29-issue-308-workbench-small-gaps.md, thoughts/shared/plans/2026-06-01-issue-288-timeout-configuration.md, thoughts/shared/plans/2026-06-05-issue-344-error-summary-line-breaks.md, thoughts/shared/plans/2026-06-30-issue-409-robust-cicd-design.md, thoughts/shared/plans/2026-06-30-issue-410-better-version-gating-design.md, thoughts/shared/plans/2026-06-30-issue-411-remove-shiny-k8s-modes-design.md, thoughts/shared/plans/2026-07-08-issue-430-interactive-auth-headless-only.md, thoughts/shared/plans/2026-07-20-issue-484-workbench-parallel-design.md, thoughts/shared/plans/2026-07-20-issue-484-workbench-parallel-plan.md, thoughts/shared/plans/2026-07-21-issue-149-ci-integration-design.md, thoughts/shared/plans/2026-07-21-issue-149-ci-integration-plan.md, thoughts/shared/plans/2026-08-21-example-report-improvements.md
Findings: docs-hygiene#Twenty implementation plans under thoughts/ target closed or merged work
Depends on: none

## 1.9 docs-remove-validation-docs

Branch: docs-remove-validation-docs
Title: docs: delete showboat transcripts for closed issues
Body:
Deletes two Showboat-generated live-diagnosis transcripts under validation_docs/ for work that closed months ago, per the docs-hygiene review, so a newcomer doesn't mistake the directory for a live validation-in-progress log.

Verified with `uv run pytest selftests/ -v`; history is preserved in git.

Files: validation_docs/demo-477-positron-console.md, validation_docs/demo-workbench-parallel-484.md
Findings: docs-hygiene#validation_docs/ holds two showboat transcripts for closed issues
Depends on: none

## 1.10 docs-remove-orphan-redirect-stubs

Branch: docs-remove-orphan-redirect-stubs
Title: docs: delete six unlinked docs redirect stubs
Body:
Deletes six docs/*.md files that only say "this documentation has moved to the website" and are linked from nowhere in the repo, README, or website, per the docs-hygiene review; Ian confirmed these should be deleted rather than replaced with an index, since the content already lives on the website.

Verified with `uv run pytest selftests/ -v` and a repo-wide `git grep` confirming no remaining reference to any of the six filenames.

Files: docs/authentication.md, docs/configuration.md, docs/deployment-verification.md, docs/getting-started.md, docs/test-categories.md, docs/reporting.md
Findings: docs-hygiene#Six docs/*.md files are pure redirect stubs, unlinked from anywhere in the repo or website
Depends on: none

## 1.11 docs-fix-stale-references

Branch: docs-fix-stale-references
Title: docs: fix commands and paths that no longer match the code
Body:
Fixes the extension-example READMEs' vip verify --collect-only command (missing the -- pytest-arg separator, so it errors as written), corrects .claude/agents/test-architect.md's pointer to fixtures that moved out of src/vip_tests/conftest.py years ago and its instruction to use bare pytest.skip() where AGENTS.md now mandates vip.attest, and removes the se-overview presentation's reference to the removed vip app Shiny UI, per the docs-hygiene review.

Verified by running the corrected command live (`uv run vip verify --config vip.toml.example --extensions examples/custom_tests -- --collect-only`) and with `uv run pytest selftests/ -v`.

Files: examples/custom_tests/README.md, examples/cross_product_validation/README.md, .claude/agents/test-architect.md, presentations/se-overview/index.qmd
Findings: docs-hygiene#Both extension-example READMEs document a vip verify command that fails as written; docs-hygiene#.claude/agents/test-architect.md points at a fixture location that no longer holds any Given-steps or fixtures; docs-hygiene#.claude/agents/test-architect.md tells agents to use bare pytest.skip(), contradicting AGENTS.md's documented policy; docs-hygiene#se-overview presentation still advertises a removed `vip app` Shiny UI
Depends on: none

## 1.12 ci-tooling-docs-workflow-index

Branch: ci-tooling-docs-workflow-index
Title: ci: document 11 missing workflow files and fix just --list text
Body:
Adds one bullet per undocumented workflow (publish.yml, docker.yml, connect-integration.yml, and eight others) to AGENTS.md's "CI workflows" section, which currently reads as an exhaustive index of only 10 of the repository's 21 workflow files, and reorders four justfile recipe comments so `just --list` shows a real one-line summary instead of a fragment of shell, per the ci-tooling review.

Verified with `just --list` showing corrected descriptions for relock/mock-idp-up/mock-idp-saml-up/mock-idp-totp-secret, and `uv run pytest selftests/ -v`; doc/comment-only change, CI on this branch is green.

Files: AGENTS.md, justfile
Findings: ci-tooling#AGENTS.md documents 10 of 21 workflow files, leaving release and drift-detection workflows invisible; ci-tooling#`just --list` shows a misleading one-line description for four recipes
Depends on: #661 merge (trivially rebased — different AGENTS.md sections)

## 1.13 product-tests-category-docs

Branch: product-tests-category-docs
Title: test: document config_hygiene as an eighth test category
Body:
Adds config_hygiene as an eighth row to AGENTS.md's product-test category table, which currently lists seven categories and omits the directory that test_secrets.py already lives in and that AGENTS.md's own CI-workflows section already references, per the product-tests review.

Verified with `uv run pytest selftests/ -v`; doc-only change.

Files: AGENTS.md
Findings: product-tests#`config_hygiene` is an eighth category, undocumented in AGENTS.md
Depends on: ci-tooling-docs-workflow-index (shares AGENTS.md)

## 1.14 tooling-precommit-parity

Branch: tooling-precommit-parity
Title: docs: document the pre-commit hook and how to install it
Body:
Adds a short "Pre-commit hooks (optional)" subsection to docs/development.md naming the pre-commit install command and stating that .pre-commit-config.yaml is pinned to the same ruff version CI enforces, per the ci-tooling review; Ian confirmed the file should be documented, not removed, since it is correctly pinned and would catch lint issues before CI.

Verified with `uv run pytest selftests/ -v`; doc-only change.

Files: docs/development.md
Findings: ci-tooling#`.pre-commit-config.yaml` is unreferenced and undocumented
Depends on: none

## 1.15 ci-local-parity

Branch: ci-local-parity
Title: ci: bump Dockerfile's Playwright base image to the pinned version
Body:
Bumps the Dockerfile's Playwright base image from v1.60.0 to v1.62.0-noble to match the exact-pinned playwright package version in pyproject.toml, and extends test_dependency_pins.py to assert the two stay in step, per the ci-tooling review, since a mismatch today silently wastes a browser re-download on every image build with nothing catching the drift.

Verified with `uv build`, `uv run pytest selftests/test_dependency_pins.py -v`, and `uv run pytest selftests/ -v`.

Files: Dockerfile, selftests/test_dependency_pins.py
Findings: ci-tooling#Dockerfile's Playwright base image is two minor versions behind the pinned Python package
Depends on: none

## 1.16 comments-tests-workbench-cleanup

Branch: comments-tests-workbench-cleanup
Title: docs(workbench): add the best-effort cleanup comment to six blocks
Body:
Adds the same one-line "best-effort cleanup -- don't mask the original failure/skip" comment that test_ide_launch.py and test_chronicle.py already carry to six other Workbench test files that catch the identical broad exception with no comment, per the error-handling and product-tests reviews, so a reader can tell the missing comment was an oversight rather than a sign the exception is unhandled.

Verified with `uvx ruff@0.15.0 check src/vip_tests/`, `uv run pytest src/vip_tests/ --collect-only -q`, and `uv run pytest selftests/ -v`; comment-only change, no test behavior affected.

Files: src/vip_tests/workbench/test_ide_extensions.py, src/vip_tests/workbench/test_jobs.py, src/vip_tests/workbench/test_runtime_versions.py, src/vip_tests/workbench/test_git_ops.py, src/vip_tests/workbench/test_session_capacity.py, src/vip_tests/workbench/test_session_capacity_k8s.py
Findings: error-handling#Cleanup helpers in `src/vip_tests` are inconsistently commented for the identical pattern; product-tests#Duplicated best-effort cleanup swallows every exception with no tolerance comment
Depends on: none

## 1.17 product-tests-k8s-fixture-inventory-doc

Branch: product-tests-k8s-fixture-inventory-doc
Title: test: correct the kubernetes_client fixture inventory doc
Body:
Corrects examples/_shared/AGENTS.md's fixture inventory, which documents kubernetes_client as the fixture session-capacity Kubernetes tests use even though test_session_capacity_k8s.py actually constructs its own client with different error-handling semantics, per the product-tests review, so an extension author reading the inventory doesn't look for a fixture the K8s test never calls.

Verified with `uv run pytest selftests/test_scaffold_agents_md.py -v` and `uv run pytest selftests/ -v`; doc-only change.

Files: examples/_shared/AGENTS.md
Findings: product-tests#`kubernetes_client` fixture is unused by its documented consumer; the K8s capacity test rebuilds it
Depends on: comments-tests-workbench-cleanup (shares src/vip_tests/workbench/test_session_capacity_k8s.py)

## 1.18 selftests-drift-guard-comment

Branch: selftests-drift-guard-comment
Title: test: point three constant-reusing tests at their real drift guard
Body:
Adds a one-line comment above three tests in test_cli_report.py that loop over _REPORT_TEMPLATE_FILES to point the reader at test_pyproject_force_include_matches_template_list, the sibling test that actually guards the constant's own correctness against pyproject.toml's independent force-include list, per the selftests review, so a reader doesn't mistake the three loops for that guard.

Verified with `uv run pytest selftests/test_cli_report.py -v` and `uv run pytest selftests/ -v`; comment-only change.

Files: selftests/test_cli_report.py
Findings: selftests#`_ensure_report_templates` tests iterate the same constant they assert against
Depends on: none

## 1.19 lint-ble-enable-only

Branch: lint-ble-enable-only
Title: chore(lint): enable BLE001 and mark every existing broad except
Body:
Enables ruff's BLE001 (blind-except) rule and adds `# noqa: BLE001` to each of the 122 existing `except Exception` sites, per the typing-lint and error-handling reviews and the design doc's error-handling rules, so CI rejects any new broad except from this point on while every existing one becomes a greppable, deliberate marker; the wave 2 error-handling PRs then remove those markers module by module as they narrow each site to a concrete exception type, and any marker that survives wave 2 must carry a one-line comment naming what is tolerated and why.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/` (clean with BLE001 enabled), `uv run --extra dev mypy src/vip`, `uv run pytest selftests/`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green. Comment-only markers, no runtime behavior changes.

Files: pyproject.toml, Found 121 errors., selftests/test_load_engine.py, src/vip_tests/connect/test_content_deploy.py, src/vip_tests/cross_product/test_resources.py, src/vip_tests/cross_product/test_ssl.py, src/vip_tests/helpers.py, src/vip_tests/performance/test_concurrency.py, src/vip_tests/performance/test_resource_usage.py, src/vip_tests/workbench/conftest.py, src/vip_tests/workbench/exec.py, src/vip_tests/workbench/test_auth.py, src/vip_tests/workbench/test_chronicle.py, src/vip_tests/workbench/test_git_ops.py, src/vip_tests/workbench/test_ide_extensions.py, src/vip_tests/workbench/test_ide_launch.py, src/vip_tests/workbench/test_jobs.py, src/vip_tests/workbench/test_publish_to_connect.py, src/vip_tests/workbench/test_runtime_versions.py, src/vip_tests/workbench/test_session_capacity_k8s.py, src/vip_tests/workbench/test_session_capacity.py, src/vip/auth.py, src/vip/cli.py, src/vip/clients/connect.py, src/vip/clients/workbench.py, src/vip/fixtures.py, src/vip/install/playwright.py, src/vip/load_engine.py, src/vip/load_users.py, src/vip/plugin.py, src/vip/proxy.py, src/vip/reporting.py, src/vip/workbench_ui.py
Findings: typing-lint#Cheap, safe-to-enable-whole families; error-handling#`install/runner.py` carries a `noqa: BLE001` for a rule that is not enabled yet
Depends on: none (marker lines rebase trivially over the wave 1a comment PRs that touch the same files)

## 1.20 lint-small-families

Branch: lint-small-families
Title: chore(lint): enable nine small ruff families in one PR
Body:
Enables and fixes ruff's S101, C4, RET, PIE, PGH, ISC, TID, N, and B families in one PR, each contributing 20 or fewer changed lines, per the typing-lint review and Ian's decision to bundle the smallest families rather than open nine near-empty PRs; includes renaming the ResourceProfileDisabled exception to ResourceProfileDisabledError (N818) and deleting the two genuinely dead `# noqa` comments PGH flags.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: selftests/test_auth_tls_e2e.py, selftests/test_publish_to_connect_fixtures.py, src/vip_tests/workbench/conftest.py
Findings: typing-lint#Cheap, safe-to-enable-whole families
Depends on: lint-ble-enable-only

## 1.21 lint-pth

Branch: lint-pth
Title: chore(lint): enable PTH (pathlib) whole
Body:
Enables and fixes ruff's PTH family repo-wide, converting the 16 flagged `os.path`-style call sites to `pathlib`, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: (16 sites identified by `uvx ruff@0.15.0 check --select PTH`; confirmed at implementation time)
Findings: typing-lint#Cheap, safe-to-enable-whole families
Depends on: lint-small-families (shares pyproject.toml)

## 1.22 lint-perf

Branch: lint-perf
Title: chore(lint): enable PERF whole
Body:
Enables and fixes ruff's PERF family repo-wide, addressing the 14 flagged performance-anti-pattern sites, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: (14 sites identified by `uvx ruff@0.15.0 check --select PERF`; confirmed at implementation time)
Findings: typing-lint#Cheap, safe-to-enable-whole families
Depends on: lint-pth (shares pyproject.toml)

## 1.23 lint-pt

Branch: lint-pt
Title: chore(lint): enable PT (pytest-style) whole
Body:
Enables and fixes ruff's PT family repo-wide (71 sites, 11 autofixable), aligning pytest idioms such as fixture and parametrize usage across the test suite, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: (71 sites identified by `uvx ruff@0.15.0 check --select PT`; confirmed at implementation time)
Findings: typing-lint#Cheap, safe-to-enable-whole families
Depends on: lint-perf (shares pyproject.toml)

## 1.24 lint-sim

Branch: lint-sim
Title: chore(lint): enable SIM (simplify) whole
Body:
Enables and fixes ruff's SIM family repo-wide (80 sites), including turning 35 `try/except/pass` blocks into `contextlib.suppress`, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: (80 sites identified by `uvx ruff@0.15.0 check --select SIM`; confirmed at implementation time)
Findings: typing-lint#Cheap, safe-to-enable-whole families
Depends on: lint-pt (shares pyproject.toml)

## 1.25 lint-pl-subset

Branch: lint-pl-subset
Title: chore(lint): enable seven low-risk PL sub-rules
Body:
Enables only the seven PL sub-rules the typing-lint review judged safe today -- PLW1510, PLR0402, PLW0108, PLR0124, PLC0207, PLR5501, and PLR1711 -- leaving PLC0415, PLR2004, PLW0603, and the PLR09* complexity family disabled since they either need the wave-2 hierarchy first or will change shape once wave 3's module splits land.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: (~30 sites identified by `uvx ruff@0.15.0 check --select PLW1510,PLR0402,PLW0108,PLR0124,PLC0207,PLR5501,PLR1711`; confirmed at implementation time)
Findings: typing-lint#PL family: only a handful of sub-rules are worth enabling now
Depends on: lint-sim (shares pyproject.toml)

## 1.26 lint-arg-vip-only

Branch: lint-arg-vip-only
Title: chore(lint): enable ARG for src/vip only
Body:
Enables ruff's ARG001/ARG002/ARG005 for src/vip only (3 real hits) and leaves them off for src/vip_tests and selftests, where the same pattern is a deliberate pytest-bdd target_fixture/ordering convention or a monkeypatch lambda shim matching a patched function's arity, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/vip/`, `uv run --extra dev mypy src/vip`, and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: src/vip/cli.py, src/vip/load_engine.py
Findings: typing-lint#ARG is a pytest-bdd/monkeypatch signature pattern, not dead parameters
Depends on: lint-pl-subset (shares pyproject.toml); comments-cli (shares src/vip/cli.py)

## 1.27 lint-d-formatting

Branch: lint-d-formatting
Title: chore(lint): autofix pydocstyle formatting repo-wide
Body:
Enables ruff's D209/D413/D403/D202/D210 repo-wide and applies the autofix, correcting whitespace and capitalization on existing docstrings across all four linted directories with no content changes, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/`, `uv run pytest selftests/ -v`, and `uv run pytest src/vip_tests/ --collect-only -q`; CI on this branch is green.

Files: (docstrings repo-wide, identified by `uvx ruff@0.15.0 check --select D209,D413,D403,D202,D210`; confirmed at implementation time)
Findings: typing-lint#D (pydocstyle): the newcomer-facing win is `src/vip` only, not the 2426 test-side hits
Depends on: lint-arg-vip-only (shares pyproject.toml)

## 1.28 lint-d-vip-docstrings

Branch: lint-d-vip-docstrings
Title: chore(lint): enable D101/D102/D103 for src/vip only
Body:
Enables ruff's D101/D102/D103 for src/vip only and adds the 92 missing docstrings the rule surfaces there, leaving src/vip_tests and selftests unselected since their 1621 hits are overwhelmingly `@scenario` stub functions where a docstring would be redundant with the Gherkin text or the test name, per the typing-lint review.

Verified with `uvx ruff@0.15.0 check src/vip/`, `uv run --extra dev mypy src/vip`, and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: (~92 sites under src/vip/, identified by `uvx ruff@0.15.0 check --select D101,D102,D103 src/vip/`; confirmed at implementation time)
Findings: typing-lint#D (pydocstyle): the newcomer-facing win is `src/vip` only, not the 2426 test-side hits
Depends on: lint-d-formatting (shares pyproject.toml and likely several src/vip/ files whose docstrings both PRs touch)

## 1.29 lint-ruf-unused-noqa

Branch: lint-ruf-unused-noqa
Title: chore(lint): enable RUF100 last and delete two dead noqa comments
Body:
Enables ruff's RUF001/002/003/012/023/043/059 now and RUF100 (unused-noqa) last, after every family it references (ARG, B, BLE, D, N, PLC0415) has landed or been explicitly deferred, so `ruff --fix` doesn't delete `# noqa` comments that were pre-anchoring a rule this program enables later; deletes the two genuinely dead blanket noqas in test_auth_tls_e2e.py, per the typing-lint review's sequencing-trap finding.

Verified with `uvx ruff@0.15.0 check src/ selftests/ examples/ docker/` and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: selftests/test_auth_tls_e2e.py
Findings: typing-lint#RUF100 (unused-noqa) will misfire until the families it references are enabled
Depends on: lint-arg-vip-only, lint-small-families, lint-ble-enable-only, lint-d-vip-docstrings (all share pyproject.toml; also shares selftests/test_auth_tls_e2e.py with lint-small-families)

## 1.30 typing-mypy-free-flags

Branch: typing-mypy-free-flags
Title: chore(typing): add two zero-cost mypy flags
Body:
Adds `no_implicit_optional` and `check_untyped_defs` to [tool.mypy], both of which pass today at zero cost on src/vip and close two real gaps in what CI currently checks, per the typing-lint review; no source changes needed.

Verified with `uv run --extra dev mypy src/vip` (`Success: no issues found`) and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: pyproject.toml
Findings: typing-lint#`no_implicit_optional` and `check_untyped_defs` are free but off
Depends on: lint-ruf-unused-noqa (shares pyproject.toml)

## 1.31 typing-warn-unused-ignores

Branch: typing-warn-unused-ignores
Title: chore(typing): enable warn_unused_ignores, delete stale ignores
Body:
Adds `warn_unused_ignores = true` to [tool.mypy] and deletes the 7 of 21 `type: ignore` comments in src/vip that mypy no longer needs, per the typing-lint review, so a newcomer trusts that every remaining `type: ignore` reflects a real, current complaint rather than a stale one from before pytest's or kubernetes's stubs improved.

Verified with `uv run --extra dev mypy --warn-unused-ignores src/vip` (zero remaining warnings) and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: src/vip/clients/kubernetes.py
Findings: typing-lint#Seven of 21 `type: ignore` comments in src/vip are already stale
Depends on: typing-mypy-free-flags (shares pyproject.toml); comments-cli (shares src/vip/cli.py); comments-fixtures-proxy-plugin (shares src/vip/plugin.py); lint-arg-vip-only (shares src/vip/load_engine.py)

## 1.32 typing-widen-mypy-scope

Branch: typing-widen-mypy-scope
Title: chore(typing): widen mypy to src/vip_tests and selftests
Body:
Widens ci.yml's mypy step to cover src/vip_tests and selftests, and fixes the 14 real errors that surface across 9 files, per the typing-lint review, closing the gap where a newcomer can introduce a real type bug in either directory today with no CI check catching it.

Verified with `uv run --extra dev mypy src/vip src/vip_tests selftests` (zero errors) and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: .github/workflows/ci.yml, src/vip_tests/connect/bundles.py, src/vip_tests/connect/test_system_checks.py, src/vip_tests/connect/test_content_deploy.py, selftests/install/test_runner.py, selftests/test_workbench_login.py, selftests/test_workbench_parallel.py, selftests/test_cli_verify.py
Findings: typing-lint#Widening mypy to src/vip_tests and selftests is cheap
Depends on: typing-warn-unused-ignores (shares pyproject.toml); lint-small-families (shares src/vip_tests/workbench/conftest.py); comments-tests-workbench-cleanup (shares src/vip_tests/workbench/test_session_capacity.py)

## 1.33 typing-strict-load-engine

Branch: typing-strict-load-engine
Title: chore(typing): apply strict mypy flags to the load module
Body:
Adds `disallow_untyped_defs`, `disallow_any_generics`, and `warn_return_any` scoped to load_engine.py and load_users.py via a per-module pyproject.toml override, fixing the 81 errors that concentrate there, per the typing-lint review, rather than reaching for `--strict` across all of src/vip where the rest is already nearly clean under those flags.

Verified with `uv run --extra dev mypy src/vip` (zero errors under the scoped strict flags) and `uv run pytest selftests/ -v`; CI on this branch is green.

Files: src/vip/load_users.py
Findings: typing-lint#mypy strict-flag costs, individually
Depends on: typing-widen-mypy-scope (shares pyproject.toml); lint-arg-vip-only (shares src/vip/load_engine.py); typing-warn-unused-ignores (both touch load_engine.py's type:ignore, resolved already in 1.31)

## GitHub issues to file (drafts for Ian)

### `_on_login_page` keyword drift between auth.py and workbench/conftest.py

`src/vip/auth.py:1329` defines `_LOGIN_KEYWORDS = ("sign-in", "login", "auth-sign-in", "/saml/acs")`, where `/saml/acs` was added as part of the fix for issue #263 (Workbench's SAML Assertion Consumer Service endpoint). `src/vip_tests/workbench/conftest.py:444` defines an identically-named `_LOGIN_KEYWORDS = ("sign-in", "login", "auth")` with a byte-identical `_on_login_page` function body, but without `/saml/acs`. The two copies have silently diverged: a fix landed in one and not the other. A pending structural PR (`structure-workbench-conftest`, VIP quality program wave 3) deduplicates the function into one shared helper while preserving both keyword tuples exactly as they are today, so this issue is scoped narrower than that PR: decide whether `workbench/conftest.py`'s copy should also recognize `/saml/acs`, the way `auth.py`'s copy already does, or whether the two call sites genuinely need different keyword sets and that should be documented instead.

### `vip/workbench_ui.py` imports test-layer Page Objects, inverting the framework/test dependency direction

`src/vip/workbench_ui.py:36` contains `from vip_tests.workbench.pages import Homepage, LoginPage`. Every other module under `src/vip/` is framework code that `src/vip_tests/` depends on; this is the one import that runs the dependency backwards, with the framework's session-cleanup helper (`quit_vip_sessions_via_ui`) reaching into the test suite's page objects. VIP's own documented four-layer test architecture places `src/vip/clients/` as Layer 3 (Driver Port) and Playwright/httpx as Layer 4 (Driver Adapter), with `src/vip_tests/**` (Layers 1-2, the test and DSL layers) depending on `src/vip/`, never the reverse. As a result, `vip/workbench_ui.py` cannot be imported or fully understood without also loading test-suite code, and any future move of `src/vip_tests/workbench/pages.py` would break a framework module instead of a test module. Fix by moving `Homepage`/`LoginPage` into `src/vip/clients/` or a new `src/vip/pages.py`, or by moving `quit_vip_sessions_via_ui` down into `src/vip_tests/workbench/`; either is a behavior-neutral file move.

### VS Code IDE-load wait reports "not installed" for any failure, and should use attest.unproven

`src/vip_tests/workbench/test_publish_to_connect.py:318-324` wraps a Playwright wait with a bare `except Exception:` and reports `pytest.skip("VS Code did not load within timeout -- the IDE may not be installed on this Workbench instance")` regardless of what actually failed. The same file narrows to `except (PlaywrightTimeoutError, PlaywrightError)` three lines above at line 296 for an equivalent wait, so the correct pattern and its violation sit side by side in one file. A locator typo, a Playwright API change, or a genuine product bug inside the wait all report identically as "IDE not installed," and the run stays green. Separately, VIP's `vip.attest.unproven()` helper exists for exactly "VIP was asked to check something and could not," which this site should use once the except is narrowed, instead of a bare skip that always looks like "not applicable." A fix for this (`errors-fix-vscode-load-skip`, VIP quality program wave 2) is already scheduled: it narrows the except to the real timeout condition, converts a genuine load failure to `attest.unproven`, and adds the file to `selftests/test_skip_triage.py`'s triaged-files list.

### TLS certificate verification failure passes security/test_https.py silently instead of failing

`src/vip_tests/security/test_https.py:137-140` catches a TLS verification failure and calls `pytest.skip(f"Could not verify TLS certificate for {product} at {pc.url}: {exc}. " + _CERT_TRUST_HINT)`. VIP's own documented convention defines `attest.unproven()` as exactly this case -- "VIP was asked to check something and could not" -- and says it should fail the run (exit code 6) unless `--allow-unproven` is passed, specifically so an unverified deployment cannot report itself as passing. Today, a deployment with a broken or self-signed certificate the operator never intended to allow passes this security check silently instead of failing loud or requiring an explicit override. The whole file has never adopted the `attest` helper (zero calls anywhere in it); its other four bare skips (lines 48, 52, 116) should be audited for the same not_applicable-vs-unproven judgment call as a follow-up, separate from this issue's scope. A fix for the line-137 site (`errors-fix-tls-verify-unproven`, VIP quality program wave 2) is already scheduled.

### Date-stamped empirical claim in a retry-match comment will go stale

`src/vip_tests/connect/test_content_deploy.py:52-56` contains a comment beginning "Filed as insurance, not a fix for chronic pain: as of 2026-07-29, this will go stale as more runs accumulate: re-run `gh run list --workflow connect-smoke.yml`..." embedded in an otherwise well-reasoned 52-line comment block (lines 28-79) explaining a deliberately narrow retry-match pattern. The comment hands the reader a manual re-verification chore but nothing ever prompts that re-check. Months from now, a reader will either trust a rotted "fired exactly once" claim or have to rediscover this warning by reading 52 lines of comment first. The retry-match rationale itself is sound and does not need to change; only the empirical claim and its expiration warning should move out of the comment and into this issue (or a periodic-check reminder the team actually revisits), so the claim gets re-verified on a cadence instead of sitting in a comment nobody is prompted to reopen.
