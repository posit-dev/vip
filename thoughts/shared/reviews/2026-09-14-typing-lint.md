# Review: typing-lint

## Summary

Ruff today only selects `E, F, I, UP`, and mypy only covers `src/vip` with no strictness flags, so the numbers in this review are the first real look at what a wider gate would surface. All counts below are from the pinned `uvx ruff@0.15.0`, matching what CI and pre-commit actually run; a plain `uv run ruff` in this worktree floats to 0.16.6 (see the version-drift finding, already fixed by open draft PR #656). The headline finding is a sequencing trap: `RUF100` (unused-noqa) looks like a free win but 24 of its 26 current hits are noqa comments pre-anchoring rules this very program plans to enable later (`ARG`, `B`, `BLE`, `D`, `N`, `PLC0415`) — enabling it first would delete comments the next PR needs. The second is that three of the largest families by violation count — `S` (3137, minus `S101`), `ARG` (463), and `PLC0415` (part of `PL`'s 1075) — are dominated by patterns that are correct in a BDD test suite (pytest-bdd step signatures, monkeypatch shims, test-scoped imports, CSS-selector strings that happen to contain the word "password"), not real defects. Mypy's easy win is `no_implicit_optional` and `check_untyped_defs`, both zero-cost on `src/vip` today, and 7 of the 21 existing `type: ignore` comments are already stale per `--warn-unused-ignores`.

## Findings

### RUF100 (unused-noqa) will misfire until the families it references are enabled
Severity: high
Evidence: ran `uv run ruff check --extend-select RUF100 src/ selftests/ examples/ docker/ --exit-zero` (this correctly layers RUF100 on top of the real `E,F,I,UP` select, unlike a bare `--select RUF100`) and grouped the messages:
```
5 non-enabled: ARG001    4 non-enabled: ARG002    1 non-enabled: B015
1 non-enabled: BLE001    1 non-enabled: D102      1 non-enabled: N801
5 non-enabled: N802      1 non-enabled: PLC0415   2 Unused blanket `noqa` directive
```
Why it matters to a newcomer: only 2 of the 26 `RUF100` hits are genuinely dead comments. The other 24 are `# noqa: ARG001`, `# noqa: N802`, etc. that someone already wrote in anticipation of rules that are not selected yet (e.g. `selftests/test_auth_tls_e2e.py:80` has `def do_GET(self):  # noqa: N802` for an `http.server` handler override). If `RUF100` is enabled as part of wave 1's "one PR per family," `ruff --fix` will delete those comments as dead weight, and the moment `N` or `ARG` lands in a later PR the same lines fail with no suppression, reopening work that looked finished.
Proposed fix: enable `RUF100` last, after every family it currently references (`ARG`, `B`, `BLE`, `D`, `N`, `PLC0415`) has landed or been explicitly rejected. Its own PR should only need to remove the 2 truly dead blanket noqas at `selftests/test_auth_tls_e2e.py:69` and `:136`.
Proposed PR: lint-ruf-unused-noqa (files: `selftests/test_auth_tls_e2e.py`, plus whatever the final-state scan finds once other families settle)

### Seven of 21 `type: ignore` comments in src/vip are already stale
Severity: high
Evidence: `uv run --extra dev mypy --warn-unused-ignores src/vip` reports:
Evidence: `src/vip/clients/kubernetes.py:20` `import kubernetes  # type: ignore[import-untyped]`
Evidence: `src/vip/plugin.py:537` `tr._get_main_color = lambda: (_current_line_color, known)  # type: ignore[method-assign]`
Evidence: `src/vip/plugin.py:541` `tr._get_main_color = original_get_main_color  # type: ignore[method-assign]`
Evidence: `src/vip/plugin.py:543` `tr._write_progress_information_filling_space = recolored_fill  # type: ignore[method-assign]`
Evidence: `src/vip/plugin.py:595` `tr._locationline = shortened  # type: ignore[method-assign]`
Evidence: `src/vip/cli.py:1086` `import tomli as _tomllib  # type: ignore[no-redef]`
Evidence: `src/vip/load_engine.py:375` `env._vip_credentials = credentials or {}  # type: ignore[attr-defined]`
Why it matters to a newcomer: every `type: ignore` reads as "mypy has a real complaint here, tolerated on purpose." A newcomer who trusts that signal will assume `tr._get_main_color` genuinely can't be typed, when mypy has stopped complaining (likely because `pytest`'s stubs, or the `kubernetes` package's own type markers, improved since the comment was written). Stale suppressions accumulate silently — nothing currently catches this drift.
Proposed fix: turn on `warn_unused_ignores = true` in `[tool.mypy]` and delete the 7 dead comments in the same PR.
Proposed PR: typing-warn-unused-ignores (files: `pyproject.toml`, `src/vip/clients/kubernetes.py`, `src/vip/plugin.py`, `src/vip/cli.py`, `src/vip/load_engine.py`)

### `no_implicit_optional` and `check_untyped_defs` are free but off
Severity: high
Evidence: `uv run --extra dev mypy --no-implicit-optional src/vip` → `Success: no issues found in 35 source files`
Evidence: `uv run --extra dev mypy --check-untyped-defs src/vip` → `Success: no issues found in 35 source files`
Why it matters to a newcomer: these two flags close two real gaps in what CI currently checks — implicit `Optional` parameters, and the bodies of any function that lacks a full annotation (mypy skips checking those bodies entirely by default, which is also why every `mypy src/vip` run above prints a wall of `annotation-unchecked` notes for `load_users.py`/`load_engine.py`). Both pass today at zero cost, so the current clean state of `src/vip` is partly an illusion: `check_untyped_defs` will start actually looking inside the untyped functions in those two files, `load_users.py` and `load_engine.py` (the locust load-test module), the moment it's on.
Proposed fix: add both flags to `[tool.mypy]` in the same PR; no source changes needed.
Proposed PR: typing-mypy-free-flags (files: `pyproject.toml`)

### TRY003/EM101/EM102 depend on the wave-2 VipError hierarchy, not a lint PR
Severity: medium
Evidence: `uv run ruff check --select TRY003 --statistics --exit-zero src/ selftests/ examples/ docker/` → `126 TRY003 raise-vanilla-args`
Evidence: `uv run ruff check --select EM101,EM102 --statistics --exit-zero src/ selftests/ examples/ docker/` → `74 EM101, 65 EM102` (139 total)
Why it matters to a newcomer: `TRY003`/`EM101`/`EM102` fire on every `raise ValueError("...")` and `raise SomeError(f"...")` with an inline message — exactly the call sites the design doc's wave 2 (`VipError` hierarchy) is meant to replace. Fixing 265 sites now, before the hierarchy exists, means writing throwaway `.args`-wrapping or module-level message constants that get thrown away again in wave 2.
Proposed fix: do not enable `TRY003`/`EM101`/`EM102` in wave 1. Hand the enumerated line list to the error-handling reviewer as raw material; enable the rules as part of (or immediately after) the wave-2 `VipError` PRs, once the exception classes exist to raise instead.
Proposed PR: none in wave 1 — defer to error-handling lens's wave-2 backlog.

### T20 (print) can't be enabled wholesale: there is no other output channel
Severity: medium
Evidence: `grep -rn "typer.echo\|rich\." src/ selftests/ examples/ docker/` → 0 matches; `grep -rln "^import rich\|^from rich" src/` → 0 matches
Evidence: `src/vip/auth.py:862` `print(">>> Please log in through your identity provider.")`
Evidence: `src/vip/auth.py:863` `print(">>> The browser will close automatically after login.\n")`
Evidence: `docker/playwright-smoke.py:61` `print(f"PASS: {label} headless chromium smoke")`
Why it matters to a newcomer: the CLI has no `typer.echo`, no `rich.Console`, and no logging framework for user-facing text — `print()` *is* the output layer for interactive auth prompts, `vip version`, and this smoke-test script. Enabling `T201` across the whole tree, as the family-per-PR ratchet implies, would flag 125 lines of intentional user-facing output as violations alongside real debug leftovers like `src/vip/auth.py:272` (`print(f">>> Warning: Could not delete API key: {exc}")` inside an `except Exception`, which arguably should be a warning through whatever channel `cli.py`'s future single error handler uses).
Proposed fix: do not enable `T201` repo-wide. If the team wants it, it requires first picking a real output abstraction (a thin `vip.output` wrapper over `print`, or adopting `typer.echo`) and routing all 125 sites through it — that is a feature, not a ratchet PR, and belongs in wave 3/4 alongside the CLI split, not wave 1.
Proposed PR: none in wave 1.

### S (bandit) is 95% test-only noise once S101 is set aside
Severity: medium
Evidence: `uvx ruff@0.15.0 check --select S105,S106 src/vip/ src/vip_tests/ --exit-zero` flags `src/vip/auth.py:1247` `password_selectors = "#password, input[name='password'], input[type='password']"` and `src/vip/idp.py:20` `_KC_PASSWORD = "input[id='password']"` — CSS selectors, not credentials
Evidence: `selftests/install/test_cli_install.py:12` `cp = subprocess.run(["uv", "run", "vip", "--help"], ...)` — flagged S607 (partial executable path) for invoking `uv`/`vip` in a test, not attacker-controlled input
Evidence: `selftests/test_reporting.py:510` `tree = ET.parse(out)` — flagged S314 for parsing VIP's own generated `junit.xml`, not untrusted data
Why it matters to a newcomer: of 3137 non-`S101` hits (`40 S110, 32 S108, 24 S106, 18 S603, 17 S607, 15 S314, 13 S105, 6 S112`), this review's samples across `S105`, `S106`, `S108`, `S314`, `S603`, `S607` did not find a single true positive — every one it inspected was a test double, a CSS selector, or a call to a known local binary. A newcomer who sees `S` mostly enabled will learn to distrust the linter rather than read it. Isolated in `src/vip` alone (excluding `vip_tests`/`selftests`), the same non-`S101` rules only produce 40 hits (`19 S110, 8 S603, 6 S607, 4 S112, 3 S105`), still dominated by the same false-positive shapes.
Proposed fix: enable only `S101` (2972 hits, 0 changes needed — asserts are correct in a pytest suite) repo-wide. Do not enable the remaining `S` rules; if the team later wants a real secrets/subprocess audit, scope it to `src/vip` only and hand-triage the 40 hits rather than accepting the family.
Proposed PR: lint-s101 (files: `pyproject.toml` only — `S101` needs no source fixes)

### ARG is a pytest-bdd/monkeypatch signature pattern, not dead parameters
Severity: medium
Evidence: `uv run ruff check --select ARG001,ARG002 src/vip/ --statistics --exit-zero` → 3 hits total in `src/vip` itself (`src/vip/cli.py:1303`, `src/vip/cli.py:1562`, `src/vip/load_engine.py:301`)
Evidence: `uv run ruff check --select ARG001,ARG002 selftests/ --statistics --exit-zero` → 268 hits (204 ARG001 + 64 ARG002)
Evidence: `src/vip_tests/connect/test_auth.py:56` `def user_authenticated(page, connect_url):` — `connect_url` is an unused pytest-bdd step argument kept for fixture ordering
Evidence: `selftests/install/test_cli_install.py:44` `monkeypatch.setattr(pw, "chromium_installed", lambda d: False)` — `ARG005`, lambda shim matching a real call signature
Why it matters to a newcomer: 460 of 463 `ARG` hits sit outside `src/vip` proper, in step definitions that intentionally take a fixture they don't reference (`target_fixture`/ordering pattern, blessed by `AGENTS.md`) and in `monkeypatch.setattr(..., lambda d: ...)` shims that must match the patched function's arity. Enabling `ARG` repo-wide would train the team to add `# noqa` to correct code.
Proposed fix: enable `ARG001`/`ARG002`/`ARG005` for `src/vip` only (3 real hits, trivial fix); do not enable for `src/vip_tests` or `selftests`.
Proposed PR: lint-arg-vip-only (files: `pyproject.toml`, `src/vip/cli.py`, `src/vip/load_engine.py`)

### PLC0415 (import-outside-top-level) is 730 of PL's 1075 hits and mostly deliberate
Severity: medium
Evidence: `uv run ruff check --select PLC0415 --statistics --exit-zero src/ selftests/ examples/ docker/` → `730 PLC0415`
Evidence: file-count breakdown (`--output-format=concise`): `199 selftests/test_auth.py`, `111 src/vip`, `85 selftests/test_cli_verify.py`, `44 selftests/test_workbench_cleanup.py`, `4 src/vip_tests` — 619 of 730 are in `selftests/`
Evidence: `src/vip/auth.py:204` `import json as _json` (inside a method body)
Why it matters to a newcomer: in `selftests/`, the pattern is `from vip.install import playwright as pw` written inside the test function right before `monkeypatch.setattr(pw, ...)` — scoping the import to the test that patches it is a deliberate isolation choice, not an oversight. In `src/vip` the 111 hits need a real look before enabling: some (like the `json` imports in `auth.py`) may be there to avoid a startup-time import in a CLI that doesn't always need `json`, others may just be forgotten top-level moves — this review did not have budget to classify all 111 individually.
Proposed fix: do not enable `PLC0415` repo-wide or as part of the `PL` family PR. If wanted for `src/vip`, triage the 111 hits by hand first (structure reviewer may already be touching several of these files for the `auth.py` split).
Proposed PR: none in wave 1 — flag the 111 `src/vip` sites for the structure reviewer to consider during the `auth.py`/`plugin.py` split.

### PL family: only a handful of sub-rules are worth enabling now
Severity: medium
Evidence: `uvx ruff@0.15.0 check --select PL --statistics --exit-zero src/ selftests/ examples/ docker/` full breakdown:
```
730 PLC0415  236 PLR2004  36 PLR0913  15 PLR0912  14 PLW1510
 12 PLR0915   9 PLR0402   5 PLR0911   5 PLW0108   5 PLW0603
  2 PLR0124   2 PLW2901   1 PLC0207   1 PLR1711   1 PLR5501   1 PLW0406
```
Note: on the unpinned `uv run ruff` (0.16.6 at time of review), this same command also reports `20 PLR0917` (too-many-positional-arguments), a rule that doesn't exist in the pinned 0.15.0 — a good concrete example of why the version pin matters for anyone re-running these numbers before #656 merges. All counts and the total below are the pinned 0.15.0 figures.
Why it matters to a newcomer: `PLC0415` (deferred above) and `PLR2004` (magic-value-comparison, 236 hits — largely test assertions like `assert resp.status_code == 404`, which is idiomatic pytest, not a magic-number smell) together are 966 of 1075 hits and both are weak signal here. `PLW1510` (subprocess-run-without-check, 14 hits) is a real risk: a `subprocess.run(...)` whose non-zero exit is silently ignored is exactly the kind of swallowed failure the error-handling lens is looking for.
Proposed fix: enable `PLW1510` (14, real bugs), `PLR0402` (9, mechanical `manual-from-import`, autofixable), `PLW0108` (5, `unnecessary-lambda`, autofixable), `PLR0124` (2, `comparison-with-itself`, real bugs), `PLC0207` (1, autofixable), `PLR5501`/`PLR1711` (2, autofixable). Do not enable `PLC0415`, `PLR2004`, `PLW0603` (global-statement, 5 — likely deliberate in the plugin's terminal-reporter monkeypatching, verify before touching), or the `PLR09*` complexity family (`PLR0913/0912/0915/0911`, 68 combined on 0.15.0) until wave 3's module splits land, since those thresholds will change shape mid-refactor. If `PLR0917` reappears once the project's pinned ruff version is next bumped, re-triage it alongside the rest of `PLR09*` rather than assuming it's covered by this recommendation.
Proposed PR: lint-pl-subset (files: `pyproject.toml` plus the ~30 sites the 6 enabled sub-rules touch)

### D (pydocstyle): the newcomer-facing win is `src/vip` only, not the 2426 test-side hits
Severity: medium
Evidence: `uv run ruff check --select D101,D102,D103 src/vip/ --statistics --exit-zero` → `49 D102, 32 D103, 11 D101` (92 total)
Evidence: `uv run ruff check --select D101,D102,D103 src/vip_tests/ --statistics --exit-zero` → `294 D103`
Evidence: `uv run ruff check --select D101,D102,D103 selftests/ --statistics --exit-zero` → `968 D102, 231 D103, 128 D101` (1327 total)
Evidence: `src/vip_tests/config_hygiene/test_secrets.py:14` `def test_no_plaintext_secrets():` with body `pass` (the `@scenario` glue function pytest-bdd requires) — flagged D103, docstring would add nothing
Why it matters to a newcomer: the design's goal is "a newcomer can read a module... and trust" — that argues for real docstrings on `src/vip`'s 92 undocumented public classes/functions/methods, which are the framework surface a newcomer actually calls into. The 1621 hits in `src/vip_tests`/`selftests` are overwhelmingly `@scenario` stub functions and test classes/methods, where a docstring is either redundant with the Gherkin scenario text or with the test name.
Proposed fix: enable `D101`/`D102`/`D103` for `src/vip` only (92 sites, real value). Separately, the auto-fixable formatting rules (`D209` new-line-after-last-paragraph 289, `D413` 21, `D403` 12, `D202` 6, `D210` 4 — 332 of the fixable 328 reported by `--statistics` are pure whitespace/capitalization, no content needed) are safe repo-wide as a mechanical PR since they touch existing docstrings only, not the 1621 missing ones.
Proposed PR: lint-d-vip-docstrings (files: `pyproject.toml`, ~92 sites under `src/vip/`), lint-d-formatting (files: `pyproject.toml`, autofix output across all four directories)

### FBT (boolean trap) concentration matches the auth.py split target
Severity: low
Evidence: `uv run ruff check --select FBT001,FBT002,FBT003 src/ selftests/ examples/ docker/ --output-format=concise --exit-zero` → 20 of 82 hits in `src/vip/auth.py`, 0 in `src/vip/cli.py`
Evidence: `src/vip/auth.py:721` `inferred: bool,` (positional bool parameter)
Why it matters to a newcomer: `cli.py`'s Typer commands show zero `FBT` hits, so this isn't a false-positive-on-CLI-flags problem the way it can be in other Typer codebases. The 20 real hits cluster in `auth.py`, corroborating the structure reviewer's case for splitting that module — a keyword-only cleanup there is cheap to fold into the same PRs that split it out.
Proposed fix: enable `FBT001`/`FBT002`/`FBT003` for `src/vip` only; fix inline with (or just before) the wave-3 `auth.py` split rather than as a standalone wave-1 PR, since call sites will move anyway.
Proposed PR: defer to wave 3, tag onto the `auth.py`-split PR(s) from the structure lens.

### Cheap, safe-to-enable-whole families
Severity: low
Evidence: `B` 7 (`4 B017 assert-raises-exception` in `selftests/test_auth.py:2676,2694,2728,2754` — all `pytest.raises(Exception)` worth narrowing once wave 2 exists, `2 B011 assert-false` in `src/vip_tests/connect/test_packages.py:115` and `src/vip_tests/cross_product/test_integration.py:69`, `1 B904` in `src/vip_tests/workbench/conftest.py:1035`)
Evidence: `C4` 2, `RET` 9, `PTH` 16, `PIE` 3, `PERF` 14, `N` 3 (2 real `N802` at `selftests/test_publish_to_connect_fixtures.py:145,163`, both test method names mirroring an `app.R` filename — judgment call whether renaming helps or hurts; 1 real `N818` at `src/vip_tests/workbench/conftest.py:280` `class ResourceProfileDisabled(Exception):`, should probably become `ResourceProfileDisabledError`), `PT` 71 (mechanical, 11 autofixable), `SIM` 80 (35 `SIM105` suppressible-exception overlaps with wave-2 except-narrowing but is independently safe today — turns `try/except/pass` into `contextlib.suppress`), `PGH` 2 (both `# noqa` with no code, `selftests/test_auth_tls_e2e.py:69,136`), `ISC` 0, `TID` 0
Why it matters to a newcomer: none of these need design decisions — they're small, every fix is a straightforward improvement, and none collide with wave 2/3 plans the way `TRY`/`EM`/`BLE`/`PLC0415` do. `BLE001` (121 hits, e.g. `src/vip/auth.py:271` `except Exception as exc:` before `print(f">>> Warning: ...")`) is the one family here that's large and real, but it's explicitly the enumeration wave 2 depends on ("Depends on wave 1 lint (BLE001) to enumerate every site" per the design doc) — enable it, but expect the fixes themselves to land in wave 2, not wave 1, per that doc's own sequencing.
Proposed fix: one ruff-family PR each for `B`, `C4`, `RET`, `PTH`, `PIE`, `PERF`, `N`, `PT`, `SIM`, `PGH`, `ISC`, `TID`, and `BLE` (enable-only, no fix, per the design doc's own wave-2 dependency).
Proposed PR: lint-b, lint-c4, lint-ret, lint-pth, lint-pie, lint-perf, lint-n, lint-pt, lint-sim, lint-pgh, lint-isc-tid, lint-ble-enable-only

### mypy strict-flag costs, individually
Severity: medium
Evidence: `uv run --extra dev mypy --disallow-untyped-defs src/vip` → `Found 42 errors in 6 files`
Evidence: `uv run --extra dev mypy --disallow-any-generics src/vip` → `Found 39 errors in 12 files` (e.g. `src/vip/load_engine.py:257` `Missing type arguments for generic type "dict"`)
Evidence: `uv run --extra dev mypy --warn-return-any src/vip` → `Found 26 errors in 6 files`
Evidence: `uv run --strict src/vip` (all flags together) → `Found 119 errors in 18 files`, broken down `42 no-untyped-def, 39 type-arg, 26 no-any-return, 7 unused-ignore, 4 misc, 1 no-untyped-call`
Why it matters to a newcomer: `--strict` looks like 119 separate problems, but it's really 4 flags' worth of errors (`disallow_untyped_defs`, `disallow_any_generics`, `warn_return_any`, `warn_unused_ignores`), and two of those (42 + 39 = 81) concentrate in `src/vip/load_engine.py` and `src/vip/load_users.py` — the locust-based load-test module, which is optional and lightly typed by nature (locust itself ships weak stubs, hence the `misc` "cannot subclass HttpUser (has type Any)" errors). Widening scope to `src/vip_tests`/`selftests` (6 and 8 errors respectively, see below) is far cheaper than reaching `--strict` on `src/vip`.
Proposed fix: land `no_implicit_optional` + `check_untyped_defs` (0 cost) and `warn_unused_ignores` (7 fixes) first. Treat `disallow_untyped_defs`/`disallow_any_generics`/`warn_return_any` as a single follow-on PR scoped to `load_engine.py`+`load_users.py` (81 of 107 combined errors), separate from the rest of `src/vip` which is nearly clean under those flags already.
Proposed PR: typing-mypy-free-flags (see above), typing-strict-load-engine (files: `src/vip/load_engine.py`, `src/vip/load_users.py`, `pyproject.toml` per-module override)

### Widening mypy to src/vip_tests and selftests is cheap
Severity: medium
Evidence: `uv run --extra dev mypy src/vip_tests` → `Found 6 errors in 5 files (checked 79 source files)`: `src/vip_tests/connect/bundles.py:61` (arg-type), `src/vip_tests/connect/test_system_checks.py:71` (dict-item), `src/vip_tests/connect/test_content_deploy.py:207` (no-redef), `src/vip_tests/workbench/conftest.py:796` (arg-type, `StorageState` vs `dict[Any, Any]`), `src/vip_tests/workbench/test_session_capacity.py:253` and `:271` (arg-type, `str | None` where `str` expected)
Evidence: `uv run --extra dev mypy selftests` → `Found 8 errors in 4 files (checked 76 source files)`: `selftests/install/test_runner.py:104,125,126,127,348` (5x union-attr, `Manifest | None` unguarded), `selftests/test_workbench_login.py:32` ("bool" not callable), `selftests/test_workbench_parallel.py:169` (var-annotated), `selftests/test_cli_verify.py:17` (var-annotated)
Why it matters to a newcomer: 14 total errors across 158 currently-untyped-in-CI files is a very small fix set for a large scope increase — right now a newcomer can introduce a real type bug in `src/vip_tests` or `selftests` and CI won't catch it. `selftests/test_workbench_login.py:32` (`"bool" not callable`) is worth a manual look — that shape usually means a fixture or mock is shadowing a callable with its boolean return value.
Proposed fix: widen `ci.yml`'s `mypy` step to `mypy src/vip src/vip_tests selftests`, fix the 14 errors in the same PR.
Proposed PR: typing-widen-mypy-scope (files: `.github/workflows/ci.yml`, `src/vip_tests/connect/bundles.py`, `src/vip_tests/connect/test_system_checks.py`, `src/vip_tests/connect/test_content_deploy.py`, `src/vip_tests/workbench/conftest.py`, `src/vip_tests/workbench/test_session_capacity.py`, `selftests/install/test_runner.py`, `selftests/test_workbench_login.py`, `selftests/test_workbench_parallel.py`, `selftests/test_cli_verify.py`)

### Ruff local version drifts ahead of the CI/pre-commit pin
Severity: medium
Evidence: `pyproject.toml:65` `"ruff>=0.15.0,<0.17"` (floating) vs `.pre-commit-config.yaml` `rev: v0.15.0` and `.github/workflows/ci.yml:59,65` `version: "0.15.0"` (hard-pinned); `uv run ruff --version` resolved `ruff 0.15.5` early in this review and `ruff 0.16.6` later in the same session, with no dependency change in between — the floating range lets `uv sync` pick up a new ruff release mid-session
Evidence: the drift is not cosmetic — this review's own `PL` numbers moved by exactly one rule between versions: `uv run ruff` (0.16.6) reports `20 PLR0917` (too-many-positional-arguments) that `uvx ruff@0.15.0` does not recognize at all, changing the family's total from 1075 to 1095
Why it matters to a newcomer: `just lint`/`just fix` resolve `uv run ruff` from whatever `uv sync` last installed under the floating `dev` extra range, so a newcomer's local run can silently gain or lose rules relative to what CI and pre-commit actually enforce (both hard-pinned to 0.15.0) — exactly the failure mode that motivated the CI comment in `AGENTS.md` ("do not change the version without updating ci.yml").
Proposed fix: already in flight — open draft PR #656 pins `pyproject.toml`'s `dev` extra to `ruff==0.15.0`, switches the justfile's ruff recipes to `uv run --extra dev ruff` (so they resolve the locked version instead of PATH), and relocks `uv.lock`. No new PR needed from this review.
Proposed PR: none — depends on #656.

## Proposed PRs

| slug | theme | files | est. changed lines | depends on |
|---|---|---|---|---|
| lint-s101 | enable S101 only | pyproject.toml | 5 | — |
| lint-c4 | enable C4 whole | pyproject.toml, 2 sites | 10 | — |
| lint-ret | enable RET whole | pyproject.toml, 9 sites | 15 | — |
| lint-pth | enable PTH whole | pyproject.toml, 16 sites | 30 | — |
| lint-pie | enable PIE whole | pyproject.toml, 3 sites | 10 | — |
| lint-perf | enable PERF whole | pyproject.toml, 14 sites | 40 | — |
| lint-n | enable N whole | pyproject.toml, 3 sites | 10 | — |
| lint-pt | enable PT whole | pyproject.toml, ~40 sites (11 autofix, rest manual) | 150 | — |
| lint-sim | enable SIM whole | pyproject.toml, ~50 sites | 200 | — |
| lint-pgh | enable PGH whole | pyproject.toml, selftests/test_auth_tls_e2e.py | 5 | — |
| lint-isc-tid | enable ISC+TID (0 violations) | pyproject.toml | 2 | — |
| lint-b | enable B whole | pyproject.toml, 7 sites | 20 | — |
| lint-ble-enable-only | enable BLE, no fixes (wave-2 input) | pyproject.toml | 2 | — |
| lint-arg-vip-only | enable ARG for src/vip only | pyproject.toml, src/vip/cli.py, src/vip/load_engine.py | 15 | — |
| lint-pl-subset | enable PLW1510/PLR0402/PLW0108/PLR0124/PLC0207/PLR5501/PLR1711 only | pyproject.toml, ~30 sites | 80 | — |
| lint-d-formatting | enable D209/D413/D403/D202/D210 (autofix, all dirs) | pyproject.toml, docstrings repo-wide | 350 | — |
| lint-d-vip-docstrings | enable D101/D102/D103 for src/vip only | pyproject.toml, ~92 sites under src/vip/ | 300 | lint-d-formatting (touches same lines) |
| typing-mypy-free-flags | no_implicit_optional + check_untyped_defs | pyproject.toml | 2 | — |
| typing-warn-unused-ignores | warn_unused_ignores + delete 7 stale ignores | pyproject.toml, src/vip/clients/kubernetes.py, src/vip/plugin.py, src/vip/cli.py, src/vip/load_engine.py | 10 | — |
| typing-widen-mypy-scope | mypy over src/vip_tests + selftests, fix 14 errors | .github/workflows/ci.yml, 9 source files | 60 | — |
| typing-strict-load-engine | disallow_untyped_defs/disallow_any_generics/warn_return_any scoped to load module | pyproject.toml, src/vip/load_engine.py, src/vip/load_users.py | 150 | typing-warn-unused-ignores |
| lint-ruf-unused-noqa | enable RUF001/002/003/012/023/043/059 now; RUF100 last | pyproject.toml, ~14 sites | 40 | lint-arg-vip-only, lint-b, lint-ble-enable-only, lint-d-vip-docstrings, lint-n |

## Not findings

- All 21 `type: ignore` comments already carry an explicit error code (`grep -rnE "type: ignore($|[^[])" src selftests` matched nothing) — no bare/blanket ignores to chase.
- No 3.11+ syntax has slipped past the `python_version = "3.10"` floor: every `tomllib`/`tomli` site correctly branches on Python version, and no `match` statements or `except*` exist anywhere in the tree.
- `requires-python = ">=3.10"` and `mypy`'s `python_version = "3.10"` agree.
- `docker/playwright-smoke.py` and the three `scripts/*.py` files outside the four linted directories are already clean under the current `E,F,I,UP` select (checked with the pinned `uvx ruff@0.15.0`) — the AGENTS.md warning about forgetting `docker/` is about the check command's arguments, not an existing gap.
- `[tool.ruff] src = ["src", "selftests", "examples"]` omits `"docker"` from the isort first-party root list, but `docker/playwright-smoke.py` doesn't import any `vip` package, so this has no observable effect today.
- `cli.py`'s Typer commands produce zero `FBT` hits — the boolean-trap rule is not going to fight with Typer's `Annotated[bool, typer.Option(...)]` pattern.
- `.pre-commit-config.yaml` has no `files`/`exclude` restricting it to the four linted directories, but since pre-commit only ever runs against staged files this doesn't diverge from CI in practice.
