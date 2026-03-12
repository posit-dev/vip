# CHANGELOG


## v0.4.0 (2026-03-12)

### Features

- **report**: Enhanced error reporting with troubleshooting hints
  ([#68](https://github.com/posit-dev/vip/pull/68),
  [`29d12ae`](https://github.com/posit-dev/vip/commit/29d12ae196b320112259dcc64c9f6634cfb9530f))


## v0.3.0 (2026-03-12)

### Features

- **website**: Add test inventory page ([#67](https://github.com/posit-dev/vip/pull/67),
  [`b9161a2`](https://github.com/posit-dev/vip/commit/b9161a2e6d657cca7f3ed9511659f7463c189b2a))


## v0.2.1 (2026-03-12)

### Bug Fixes

- **website**: Fix index page layout rendering ([#66](https://github.com/posit-dev/vip/pull/66),
  [`4d8e0a8`](https://github.com/posit-dev/vip/commit/4d8e0a87235839893991a71f15c50e1ed00ddf77))

### Chores

- **deps**: Bump the actions-dependencies group with 9 updates
  ([#64](https://github.com/posit-dev/vip/pull/64),
  [`c7c5944`](https://github.com/posit-dev/vip/commit/c7c594426bfcbf4d3dd83765f87479ff606300d8))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>


## v0.2.0 (2026-03-12)

### Continuous Integration

- Add status gate jobs to smoke test workflows ([#70](https://github.com/posit-dev/vip/pull/70),
  [`9d7d441`](https://github.com/posit-dev/vip/commit/9d7d4412d79bc7995ff0682dd67a806f79905eb5))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

- Configure dependabot for conventional commits and skip smoke tests
  ([#69](https://github.com/posit-dev/vip/pull/69),
  [`4704324`](https://github.com/posit-dev/vip/commit/47043249e19c8ff079dd0ad5b902013cafff4008))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

- Workbench smoke test ([#10](https://github.com/posit-dev/vip/pull/10),
  [`b433483`](https://github.com/posit-dev/vip/commit/b433483a244a52fafe9fc1086a95599dc9ab6bd0))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

### Features

- Run RSPM tests in report preview and remove dependabot skip from smoke tests
  ([#71](https://github.com/posit-dev/vip/pull/71),
  [`934729d`](https://github.com/posit-dev/vip/commit/934729d55984e51cb16cf9f4be164ac6b1cb9450))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>


## v0.1.2 (2026-03-11)

### Bug Fixes

- Separate execution modes and fix credential wiring
  ([#59](https://github.com/posit-dev/vip/pull/59),
  [`c086dce`](https://github.com/posit-dev/vip/commit/c086dce6dbc5fd83dfea33d092e92164f708ea4a))

* Fix credential Secret key names to match expected env vars

Both credential paths wrote K8s Secret keys that did not match the env var names config.py reads via
  envFrom. Keycloak wrote "username"/ "password"; interactive wrote
  "connect-api-key"/"pm-token"/etc. Rename all keys to VIP_TEST_USERNAME, VIP_TEST_PASSWORD,
  VIP_CONNECT_API_KEY, VIP_WORKBENCH_API_KEY, VIP_PM_TOKEN so the Secret mounts correctly as
  environment variables.

* Always mount credentials Secret in K8s Job

The envFrom mount was conditionally skipped when interactive_auth=True, meaning credentials written
  by the interactive path were never exposed to the Job container. Both credential paths write to
  the same Secret, so always mount it. Remove the interactive_auth parameter from create_job.

* Add Mode enum and per-mode config validation

Introduce Mode(str, Enum) with local, k8s_job, and config_only values and a
  VIPConfig.validate_for_mode() method that raises ValueError when required fields are missing for
  the requested mode. k8s_job and config_only modes require cluster configuration.

* Split run_verify into named phase functions

Break the monolithic run_verify into _resolve_mode, _phase_generate_config,
  _phase_provision_credentials, and _phase_run_tests. run_verify becomes a thin orchestrator that
  resolves the mode, validates config, and delegates to each phase. Update CLI help text to document
  execution and credential modes.

* Document execution modes and credential approaches

Add mode/credential matrix to vip.toml.example explaining the three execution modes and two
  credential approaches. Update cluster section comments to clarify when it is required. Update key
  source files table to reflect Mode enum in config.py.

* Address PR review: gate cluster connect by mode, detect stale Secret keys

Skip cluster connection in local mode since it's unnecessary. Detect old-format Secret key names
  (username/password) and warn users to run `vip verify cleanup` to regenerate.


## v0.1.1 (2026-03-11)

### Bug Fixes

- Use SSH deploy key for semantic-release push ([#65](https://github.com/posit-dev/vip/pull/65),
  [`4a224ff`](https://github.com/posit-dev/vip/commit/4a224ffe7e8bf430a9d931da297dbfd18c54d21b))

* Add semantic release with conventional commit enforcement

Configure python-semantic-release for v0.x.x versioning, add a GitHub Actions release workflow using
  a deploy key for tag pushing, and enforce conventional commits on PRs via commitlint.

* Replace commitlint with PR title check to match team-operator pattern

Squash merges use the PR title as the commit message, so enforce conventional format there instead
  of on individual commits.

* Fix semantic-release push: use SSH deploy key instead of HTTPS token

* Address review feedback on release workflow

Remove unused id-token permission, pin python-semantic-release to 9.21.0, and skip workflow on
  chore(release) commits to prevent recursive triggers.

### Continuous Integration

- Add Dependabot config for dependency updates ([#61](https://github.com/posit-dev/vip/pull/61),
  [`1101728`](https://github.com/posit-dev/vip/commit/11017286613d8abf06d98e78b79cec1550a46d9b))

* Add Dependabot config for automated dependency updates

Configure uv and github-actions ecosystems with grouped updates, 7-day cooldown for version updates,
  and weekly schedule. Security updates bypass the cooldown and arrive immediately.

* Add agent tooling paths to .gitignore

* docs: add PR title convention to AGENTS.md

Document the conventional commit format required by pr-title.yml so agents and contributors know the
  expected format.

- Add semantic release with conventional commit enforcement
  ([#58](https://github.com/posit-dev/vip/pull/58),
  [`481ff0d`](https://github.com/posit-dev/vip/commit/481ff0d50dbf3aa85b976a81b395c7800861039f))

* Add semantic release with conventional commit enforcement

Configure python-semantic-release for v0.x.x versioning, add a GitHub Actions release workflow using
  a deploy key for tag pushing, and enforce conventional commits on PRs via commitlint.

* Replace commitlint with PR title check to match team-operator pattern

Squash merges use the PR title as the commit message, so enforce conventional format there instead
  of on individual commits.

### Documentation

- Remove all PTD references from documentation and source comments
  ([#62](https://github.com/posit-dev/vip/pull/62),
  [`2c7c284`](https://github.com/posit-dev/vip/commit/2c7c284424556c45431c18d940302d95285da917))

* Initial plan

* Remove all PTD references from documentation and source code comments

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>

---------

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>


## v0.1.0 (2026-03-10)
