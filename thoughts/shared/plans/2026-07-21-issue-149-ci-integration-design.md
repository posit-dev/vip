# Design — #149: CI pipeline integration (machine-readable output + container entrypoint)

**Status:** Approved design (brainstorming) — ready for implementation plan
**Date:** 2026-07-21
**Issue:** posit-dev/vip#149
**Branch:** `worktree-ci-pipeline-integration-149`

## Framing

#149 asks VIP to be consumable *by* customers' security-operations and CI/CD pipelines (distinct from #409, which is about testing VIP *itself* in CI). Feedback originated from a Solutions Engineering presentation (2026-04-07); FSI (Financial Services) is the primary driver, with general security-automation enterprise as secondary.

The issue is not a single PR — it is four loosely-coupled items, one of which (`concise_error` + `failures.json`, #162) already shipped. Two more are already partially built:

- The GHCR image build/push pipeline already exists (`.github/workflows/docker.yml` pushes `ghcr.io/posit-dev/vip` on `main` and `v*` tags).
- `vip verify` is already CI-safe by default: exit codes propagate pytest's return code, and `_check_credentials()` fails fast with a non-zero exit instead of prompting when credentials are missing.

**This PR's slice** covers the remaining gaps that deliver the most secops value:

1. JUnit XML output format
2. SARIF output format
3. Container entrypoint rework (raw `pytest` → the `vip` CLI)
4. A `--ci` convenience flag + documentation

## Decisions (from brainstorming)

| Topic | Decision |
| --- | --- |
| Format selection | `vip verify --format <comma-separated>`, values `json\|junit\|sarif`, default `json`, additive |
| `json` behavior | `results.json` + `failures.json` are **always** written (the Quarto HTML report depends on `results.json`); `--format` only *adds* JUnit/SARIF |
| Output paths | Extra formats are siblings of `--report`'s directory: `<dir>/junit.xml`, `<dir>/results.sarif` — no new path flags |
| JUnit source | Custom writer off the existing `ReportData`/`TestResult` dataclasses (richer than pytest's native `--junitxml`: includes `concise_error` + scenario/feature metadata; single code path) |
| SARIF mapping | **Every check** emits a result — fail=`error`, pass=`none`, skip=`note` — for a full compliance audit trail |
| SARIF location | `logicalLocation` of `"<Product> / <check>"` (no phantom source file) |
| Container entrypoint | `ENTRYPOINT ["uv","run","vip"]`, `CMD ["verify"]` — `docker run img` runs verify; other subcommands remain reachable |
| `--ci` flag | Sugar for `--format json,junit,sarif` + explicit non-interactive + concise stdout (`--tb=short`) |

## Architecture

### 1. Writers — `src/vip/reporting.py`

Two new pure functions consuming a `ReportData` (already the deserialized model produced by `load_results()`), so they work identically whether called at pytest session end or later from a results file:

- **`write_junit_xml(data: ReportData, path: Path) -> None`**
  - Standard `testsuites > testsuite > testcase` schema.
  - `testcase`: `name` = scenario title (fallback nodeid), `classname` = feature/product, `time` = duration.
  - Children: `<failure message=concise_error>` for fails, `<error>` for errors, `<skipped>` for skips (including `na_version` skips, with the version-gate reason as the skip message).
  - Suite-level `tests`/`failures`/`errors`/`skipped` counts from `ReportData.total/failed/…`.

- **`write_sarif(data: ReportData, path: Path) -> None`**
  - SARIF 2.1.0. `runs[0].tool.driver` = `{name: "vip", version: __version__, informationUri, rules: [...]}`.
  - `rules[]`: one entry per unique check (keyed by nodeid), so results reference stable `ruleId`s.
  - `results[]`: **one per check outcome** — `level` = `error` (fail) / `none` (pass) / `note` (skip); `message.text` = `concise_error` for fails, else scenario title / skip reason; `locations[0].logicalLocation.name` = `"<Product> / <check>"`.
  - Tradeoff (accepted): `none`-level results are noisier in code-scanning UIs, but give FSI the "evidence of what was checked" audit trail they asked for.

### 2. Plugin wiring — `src/vip/plugin.py`

- Add a `--vip-format` pytest option (mirrors the existing `--vip-report` at `plugin.py:84`).
- In `pytest_sessionfinish` (`plugin.py:1048`), after the existing `results.json`/`failures.json` writes, parse the requested format list and call `write_junit_xml` / `write_sarif` for the sibling paths derived from `--vip-report`'s directory.

### 3. CLI — `src/vip/cli.py`

- `vip verify --format json,junit,sarif` → validated (reject unknown values) and forwarded as `--vip-format=…`.
- `vip verify --ci` → expands to `--format json,junit,sarif`, ensures non-interactive (no `--interactive-auth`/`--headless-auth`), and sets concise output (`--tb=short`). Mutually compatible with an explicit `--format` (explicit wins / unions — resolved in plan).

### 4. Container — `Dockerfile`

- `ENTRYPOINT ["uv","run","vip"]`, `CMD ["verify"]`.
- Config still mounted at `/app/vip.toml`.
- No change to `docker.yml` (GHCR build/push already correct). Verify `.dockerignore` doesn't exclude anything the CLI entrypoint needs at runtime.

### 5. Docs

- `README.md`: a "CI / pipeline integration" section — `docker run -v $PWD/vip.toml:/app/vip.toml ghcr.io/posit-dev/vip --ci` recipe, output-format table, and where each artifact lands.
- `AGENTS.md`: note the new `--format`/`--ci` surface if it documents CLI options.
- `CHANGELOG.md`: handled automatically by semantic-release via a `feat:` commit.
- Docs website page for `vip verify` options, if one exists.

## Testing (TDD)

New `selftests/` coverage (patterned on existing `test_reporting.py` / `test_cli_verify.py`):

- `write_junit_xml`: well-formed XML; correct suite counts; failure/error/skip element mapping; `na_version` skip reason surfaced.
- `write_sarif`: valid SARIF 2.1.0 structure; every outcome emits a result with the right `level`; `rules[]` dedup; `logicalLocation` naming.
- CLI: `--format junit,sarif` writes the sibling files and still writes `results.json`; unknown format value is rejected; `--ci` produces all three artifacts.

## Out of scope (this PR)

- Multi-arch container images.
- Promoting VIP's own smoke workflows (that is #409).
- Per-format path override flags (`--junit-xml PATH` / `--sarif PATH`) — deferred; siblings-in-report-dir is sufficient for the driving use case.
