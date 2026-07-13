# CHANGELOG


## v0.52.4 (2026-07-10)

### Bug Fixes

- **workbench**: Extensions search input selector and keyboard entry
  ([#456](https://github.com/posit-dev/vip/pull/456),
  [`5b4d200`](https://github.com/posit-dev/vip/commit/5b4d2009b259d7b86601cbf1429d9237fa38695e))


## v0.52.3 (2026-07-09)

### Bug Fixes

- **ssl**: Skip https/tls scenarios on http-only or insecure deployments
  ([#455](https://github.com/posit-dev/vip/pull/455),
  [`7902fdd`](https://github.com/posit-dev/vip/commit/7902fdd2406065c548736330494c1d85d410a6b8))

### Chores

- **deps**: Bump the actions-dependencies group across 1 directory with 6 updates
  ([#454](https://github.com/posit-dev/vip/pull/454),
  [`07450e7`](https://github.com/posit-dev/vip/commit/07450e741e006c23f45c25b309dba68739580753))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Ignore gh-aw-managed shared actions in dependabot
  ([#453](https://github.com/posit-dev/vip/pull/453),
  [`6bab845`](https://github.com/posit-dev/vip/commit/6bab8450d86c6fe618be4c78ec67f445d81033a1))

### Testing

- **workbench**: Add in-session Chronicle data-collection test
  ([#440](https://github.com/posit-dev/vip/pull/440),
  [`b0dddaa`](https://github.com/posit-dev/vip/commit/b0dddaa7648cea3ebaf13f918f9a979f93f02595))

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.52.2 (2026-07-09)

### Bug Fixes

- **workbench**: Select RStudio tab and dismiss dialog defensively
  ([#418](https://github.com/posit-dev/vip/pull/418),
  [`c580c39`](https://github.com/posit-dev/vip/commit/c580c3985284f7d0eda0d1367828f2ffd7d108fa))

Co-authored-by: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Co-authored-by: Brian Deitte <brian.deitte@posit.co>

### Continuous Integration

- Ignore actions/cache in dependabot (gh-aw lockfile guard)
  ([#451](https://github.com/posit-dev/vip/pull/451),
  [`c25d276`](https://github.com/posit-dev/vip/commit/c25d276c2b2cdf5f066c85e9dc108178a109f84f))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>


## v0.52.1 (2026-07-08)

### Bug Fixes

- **workbench**: Remove stale clone dir before git-ops clone
  ([#443](https://github.com/posit-dev/vip/pull/443),
  [`4dc896c`](https://github.com/posit-dev/vip/commit/4dc896c5892ff2d297d21d886f4d99f6313f21b2))

Co-authored-by: Claude Sonnet 5 <noreply@anthropic.com>

### Build System

- Pin uv version for deterministic uv.lock ([#442](https://github.com/posit-dev/vip/pull/442),
  [`721f9ce`](https://github.com/posit-dev/vip/commit/721f9ce98ed339cd24c7a13e032662574c997cce))

### Chores

- **deps**: Bump the python-dependencies group with 2 updates
  ([#446](https://github.com/posit-dev/vip/pull/446),
  [`362a65c`](https://github.com/posit-dev/vip/commit/362a65c29cf09539003f9bcc2983dbde9ef4c709))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Bump gh-aw lockfile pin to v0.81.6 and recompile
  ([#448](https://github.com/posit-dev/vip/pull/448),
  [`6559a2e`](https://github.com/posit-dev/vip/commit/6559a2e0c8d542806b8d1e36627649b71e469b0d))

### Testing

- Pin interactive-auth poll-loop detection (headless-only stance)
  ([#444](https://github.com/posit-dev/vip/pull/444),
  [`3c241a3`](https://github.com/posit-dev/vip/commit/3c241a3d758fd020d2993d7f44c754d93b12f17c))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>

- **package-manager**: Add binary package serving coverage
  ([#437](https://github.com/posit-dev/vip/pull/437),
  [`dcacaae`](https://github.com/posit-dev/vip/commit/dcacaaeb197ea956505310332438deb07b20dce2))

Co-authored-by: Claude Opus 4.8 <noreply@anthropic.com>


## v0.52.0 (2026-07-03)

### Chores

- **deps**: Bump the actions-dependencies group with 4 updates
  ([#429](https://github.com/posit-dev/vip/pull/429),
  [`63c8c5b`](https://github.com/posit-dev/vip/commit/63c8c5b9d80aae8a0aa354b49c251e7fc87fc099))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: Brian Deitte <brian.deitte@posit.co>

- **deps**: Bump the python-dependencies group across 1 directory with 4 updates
  ([#428](https://github.com/posit-dev/vip/pull/428),
  [`f7d5b78`](https://github.com/posit-dev/vip/commit/f7d5b78c23bb132269ad5fde1c457f638bffb229))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Add mock-IdP E2E stack for OIDC auth testing ([#431](https://github.com/posit-dev/vip/pull/431),
  [`4ffc741`](https://github.com/posit-dev/vip/commit/4ffc741729ed15b41a47eaa47fe957e488a3a3ad))

### Features

- **cli**: Add --connect-version and --workbench-version to vip verify
  ([#436](https://github.com/posit-dev/vip/pull/436),
  [`ac3cd02`](https://github.com/posit-dev/vip/commit/ac3cd02e3b2c4f3eb4649faf41939dcb508f150c))


## v0.51.0 (2026-07-01)

### Continuous Integration

- Skip example-report on dependabot PRs (no secret access)
  ([#433](https://github.com/posit-dev/vip/pull/433),
  [`69ac412`](https://github.com/posit-dev/vip/commit/69ac412bc8aed3480160acdbc75c41062910b926))

### Features

- Add robust version gating, N/A status, versioned page objects
  ([#432](https://github.com/posit-dev/vip/pull/432),
  [`3ab28b8`](https://github.com/posit-dev/vip/commit/3ab28b819df7580fcffd51a5ccfc430ae5eba5ae))


## v0.50.1 (2026-07-01)

### Bug Fixes

- Extend connect system checks default timeout to 5min
  ([#417](https://github.com/posit-dev/vip/pull/417),
  [`31b90a8`](https://github.com/posit-dev/vip/commit/31b90a8e37a284d1527ad94badd8a9d9ef1aece2))

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.50.0 (2026-07-01)

### Chores

- **deps**: Bump python-socketio and python-engineio for CVE fixes
  ([#424](https://github.com/posit-dev/vip/pull/424),
  [`79a4126`](https://github.com/posit-dev/vip/commit/79a41268da77e06a95e966a535ac92779adc7aec))

- **deps**: Bump the actions-dependencies group with 3 updates
  ([#408](https://github.com/posit-dev/vip/pull/408),
  [`10d6477`](https://github.com/posit-dev/vip/commit/10d64772799236e909a9b106733ad1e9b821d62d))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: Brian Deitte <brian.deitte@posit.co>

- **deps**: Bump the python-dependencies group with 6 updates
  ([#407](https://github.com/posit-dev/vip/pull/407),
  [`4950890`](https://github.com/posit-dev/vip/commit/4950890f5ff64fea29084cc51db9a808d436b4eb))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Scope PR dependency audit; add scheduled full-tree audit
  ([#426](https://github.com/posit-dev/vip/pull/426),
  [`8cb457f`](https://github.com/posit-dev/vip/commit/8cb457f181cdc52eeb33d638f0071b81c95aee61))

### Features

- Remove Shiny app and Kubernetes modes ([#423](https://github.com/posit-dev/vip/pull/423),
  [`803fed1`](https://github.com/posit-dev/vip/commit/803fed168286eae9326b92a534f790d0a0bb57dd))


## v0.49.2 (2026-06-25)

### Bug Fixes

- **plugin**: Show full skip reasons and dedup auth warning
  ([#414](https://github.com/posit-dev/vip/pull/414),
  [`1335d09`](https://github.com/posit-dev/vip/commit/1335d09093c8b2709fc73c4132c291f2e2b99ed9))


## v0.49.1 (2026-06-24)

### Bug Fixes

- **workbench**: Macos console clear, session fail-fast, ui cleanup
  ([#405](https://github.com/posit-dev/vip/pull/405),
  [`3c92deb`](https://github.com/posit-dev/vip/commit/3c92debf20f7f243c31933e0538c2fca8ed0b393))

### Continuous Integration

- Promote full connect category and PM repo tests to smoke
  ([#406](https://github.com/posit-dev/vip/pull/406),
  [`4d5898f`](https://github.com/posit-dev/vip/commit/4d5898f253de66652f805205e1aadf35e75d8fc6))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>

- Scope smoke-test filters per product and cache Playwright browsers
  ([#404](https://github.com/posit-dev/vip/pull/404),
  [`47d6652`](https://github.com/posit-dev/vip/commit/47d6652d56fe8c154055dfa08c8e5cd619dbb076))


## v0.49.0 (2026-06-24)

### Features

- **workbench**: Add anonymous git auth mode (none)
  ([#403](https://github.com/posit-dev/vip/pull/403),
  [`33bc3b1`](https://github.com/posit-dev/vip/commit/33bc3b1db60dfa17380e239d9783eab5e82b2a01))


## v0.48.3 (2026-06-24)

### Bug Fixes

- **workbench**: Type() instead of fill() for Ace console input
  ([#402](https://github.com/posit-dev/vip/pull/402),
  [`408c52d`](https://github.com/posit-dev/vip/commit/408c52db9de5d4b3d26bcb0b2df2923dce1d206a))


## v0.48.2 (2026-06-24)

### Bug Fixes

- **plugin**: Suppress pytest-bdd PytestRemovedIn10Warning on pytest 9.1
  ([#401](https://github.com/posit-dev/vip/pull/401),
  [`7a2619e`](https://github.com/posit-dev/vip/commit/7a2619e888a7cbb027dc104f2501c1351368c360))


## v0.48.1 (2026-06-24)

### Bug Fixes

- **workbench**: Support interactive auth behind an OIDC IdP
  ([#398](https://github.com/posit-dev/vip/pull/398),
  [`347433d`](https://github.com/posit-dev/vip/commit/347433dc584b0b93bd8fa734d06b05868eee17f1))


## v0.48.0 (2026-06-24)

### Chores

- **deps**: Bump the actions-dependencies group with 4 updates
  ([#395](https://github.com/posit-dev/vip/pull/395),
  [`747e18b`](https://github.com/posit-dev/vip/commit/747e18bef1652bd18401a01138f83f16716edae1))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>

- **deps**: Bump the python-dependencies group with 3 updates
  ([#394](https://github.com/posit-dev/vip/pull/394),
  [`a54af7a`](https://github.com/posit-dev/vip/commit/a54af7a29e075e05e0aa8d4f51933fcffd956e44))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Features

- Support Connect behind an OIDC forward-auth gateway
  ([#397](https://github.com/posit-dev/vip/pull/397),
  [`d759002`](https://github.com/posit-dev/vip/commit/d759002df9ef698237b08753d498f1e32d64d8a9))

### Testing

- **connect**: Add chronicle status verification ([#393](https://github.com/posit-dev/vip/pull/393),
  [`1dd5ceb`](https://github.com/posit-dev/vip/commit/1dd5cebc2c56580cd0d357d5a958d0da4c7caa64))

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.47.0 (2026-06-18)

### Features

- **cli**: Add --json output to vip status ([#396](https://github.com/posit-dev/vip/pull/396),
  [`0ded78f`](https://github.com/posit-dev/vip/commit/0ded78f4be78b01e5db8f9311497ca82964631ee))


## v0.46.3 (2026-06-16)

### Bug Fixes

- **workbench**: Route git-ops readback by detected IDE
  ([#391](https://github.com/posit-dev/vip/pull/391),
  [`5d17668`](https://github.com/posit-dev/vip/commit/5d17668f5dedc937e2f1c127a4f15c5fb22a49e3))


## v0.46.2 (2026-06-16)

### Bug Fixes

- **deps**: Bump deps to clear new pip-audit advisories
  ([#392](https://github.com/posit-dev/vip/pull/392),
  [`f8ad698`](https://github.com/posit-dev/vip/commit/f8ad698d8f9c7eb82f4f9ea34e41805d9efd9e3d))


## v0.46.1 (2026-06-13)

### Bug Fixes

- **workbench**: Fix terminal-open and SSO sign-out tests
  ([#385](https://github.com/posit-dev/vip/pull/385),
  [`49abfb8`](https://github.com/posit-dev/vip/commit/49abfb82f15797216f47247bcf82ca07df2cba57))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>


## v0.46.0 (2026-06-12)

### Continuous Integration

- Fix agentic workflow tooling and screenshot PR detection
  ([#382](https://github.com/posit-dev/vip/pull/382),
  [`43d9a84`](https://github.com/posit-dev/vip/commit/43d9a848115c518dcebabfb700e6690f04a715ff))

- Fix smoke workflow deadlock by moving path filters to job-level gate
  ([#383](https://github.com/posit-dev/vip/pull/383),
  [`4b84ac2`](https://github.com/posit-dev/vip/commit/4b84ac2b941af021393866dd57d6bb29be69c38d))

### Features

- **workbench**: Add idle session auto-suspend behavior tests (closes #305)
  ([#380](https://github.com/posit-dev/vip/pull/380),
  [`da98411`](https://github.com/posit-dev/vip/commit/da98411fa70b1d56fae6242f6a0dec6805891894))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.45.0 (2026-06-12)

### Documentation

- Plan for #305 — workbench idle session auto-suspend behavior
  ([#315](https://github.com/posit-dev/vip/pull/315),
  [`1cb7ea6`](https://github.com/posit-dev/vip/commit/1cb7ea6e52d2cb3dcd856e3e889c0af15cdba86d))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

### Features

- **timeouts**: Add VIP_TIMEOUT_SCALE env-var multiplier (closes #288)
  ([#368](https://github.com/posit-dev/vip/pull/368),
  [`6505322`](https://github.com/posit-dev/vip/commit/6505322e5d9fe66e2faf4765d24f9c7586459243))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.44.0 (2026-06-12)

### Features

- **examples**: Add custom test extension example and vip scaffold (closes #298)
  ([#374](https://github.com/posit-dev/vip/pull/374),
  [`bef4c13`](https://github.com/posit-dev/vip/commit/bef4c1345d566a649d428ad937daa74637f6894f))

- **workbench**: Add Workbench sign-out scenario (closes #308)
  ([#366](https://github.com/posit-dev/vip/pull/366),
  [`5e5db99`](https://github.com/posit-dev/vip/commit/5e5db991835f1537f0c844052c8825a3fbab3029))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.43.0 (2026-06-12)

### Features

- **workbench**: Cover Git operations from Workbench sessions (closes #306)
  ([#363](https://github.com/posit-dev/vip/pull/363),
  [`01e09b5`](https://github.com/posit-dev/vip/commit/01e09b505e2e86c529be0d0479e0bd2ccf108d96))


## v0.42.0 (2026-06-12)

### Features

- **workbench**: Publish to Connect from Workbench terminal (closes #307)
  ([#371](https://github.com/posit-dev/vip/pull/371),
  [`3a753dc`](https://github.com/posit-dev/vip/commit/3a753dc2d1665092381d0fb781ce3afde832df84))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.41.3 (2026-06-12)

### Bug Fixes

- **workbench**: Stop asserting exact username on homepage login check (closes #273)
  ([#361](https://github.com/posit-dev/vip/pull/361),
  [`66d9872`](https://github.com/posit-dev/vip/commit/66d9872a15422c112641f313b2f44987ea75fe96))


## v0.41.2 (2026-06-12)

### Bug Fixes

- **workbench**: Raise descriptive error when R console output times out (closes #275)
  ([#362](https://github.com/posit-dev/vip/pull/362),
  [`2400548`](https://github.com/posit-dev/vip/commit/2400548acbbdc95bbfe2c31bf7ee28c5c36852f9))


## v0.41.1 (2026-06-12)

### Bug Fixes

- **connect**: Skip user-list assertion when no test user is configured (closes #264)
  ([#359](https://github.com/posit-dev/vip/pull/359),
  [`2175d9f`](https://github.com/posit-dev/vip/commit/2175d9ff86dce230de07ef824fa1e12a32b0f29e))

- **ssl**: Accept HTTPS termination behind load balancers in redirect test (closes #265)
  ([#360](https://github.com/posit-dev/vip/pull/360),
  [`80e0390`](https://github.com/posit-dev/vip/commit/80e0390430647114e8b07a4b4f317b1cd6505983))

### Chores

- **deps**: Bump the actions-dependencies group across 1 directory with 4 updates
  ([#358](https://github.com/posit-dev/vip/pull/358),
  [`e0447d7`](https://github.com/posit-dev/vip/commit/e0447d74daf8c45d8d30a0efe29753a2bb9234c0))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>

- **deps**: Bump the python-dependencies group across 1 directory with 7 updates
  ([#370](https://github.com/posit-dev/vip/pull/370),
  [`567d239`](https://github.com/posit-dev/vip/commit/567d239ec045c1c064c8ed5c444098d280132b9d))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Exempt dependabot from the uv.lock guard ([#365](https://github.com/posit-dev/vip/pull/365),
  [`272840a`](https://github.com/posit-dev/vip/commit/272840acc803fc833a10ee95e7768ab160e39887))

### Documentation

- Plan for #288 — improved timeout configuration ([#332](https://github.com/posit-dev/vip/pull/332),
  [`6f59822`](https://github.com/posit-dev/vip/commit/6f5982274661b8c1ab87883b5595ab124ac2ff29))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>

- Plan for #298 — custom test extension scaffolding
  ([#299](https://github.com/posit-dev/vip/pull/299),
  [`452dae3`](https://github.com/posit-dev/vip/commit/452dae306f168d3525371b68cf98ed659501c6bb))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>

- Plan for #307 — publish to Connect from Workbench
  ([#313](https://github.com/posit-dev/vip/pull/313),
  [`426e791`](https://github.com/posit-dev/vip/commit/426e791cafba511aa850c0e2eecb0763a07f4ea5))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>

- Plan for #308 — Workbench sign-out, AI defaults, runtime extension install
  ([#310](https://github.com/posit-dev/vip/pull/310),
  [`c29865e`](https://github.com/posit-dev/vip/commit/c29865e1c05a0532fbefeec36d3458e972c69fd9))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Copilot <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>


## v0.41.0 (2026-06-11)

### Features

- **workbench**: Verify expected R/Python runtime versions (closes #303)
  ([#327](https://github.com/posit-dev/vip/pull/327),
  [`2cfed3b`](https://github.com/posit-dev/vip/commit/2cfed3b26d3c6644d6d26e17e2fc2a7cadd9f108))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>


## v0.40.0 (2026-06-10)

### Continuous Integration

- Fix gh-aw bash allowlists to permit command arguments
  ([#355](https://github.com/posit-dev/vip/pull/355),
  [`dab98d4`](https://github.com/posit-dev/vip/commit/dab98d404f05d35741fa3e78f88c8ec0c542cf03))

- Fix stale preview-screenshot lockfile and guard against drift
  ([#356](https://github.com/posit-dev/vip/pull/356),
  [`5d5f4e8`](https://github.com/posit-dev/vip/commit/5d5f4e8b283cda4c9c4eb968f19fd4195ade9fd9))

### Features

- Support Snowflake OAuth for Posit Team Native Apps
  ([#321](https://github.com/posit-dev/vip/pull/321),
  [`491aeb2`](https://github.com/posit-dev/vip/commit/491aeb278629c3b85580cfea8bbe1296adb067ad))

Adds Snowflake SPCS ingress auth support to VIP: a "snowflake" IdP strategy (multi-hop OAuth browser
  login), an injectable httpx client-auth registry, X-RSC-Authorization for Connect API keys behind
  the ingress, performance-path auth fixes, and a friendly --api-auth guard for the Snowflake IdP.
  Also documents Snowflake Native App as a supported deployment target.


## v0.39.1 (2026-06-09)

### Bug Fixes

- **plugin**: Preserve line breaks in error_summary (closes #344)
  ([#353](https://github.com/posit-dev/vip/pull/353),
  [`35e86b0`](https://github.com/posit-dev/vip/commit/35e86b08d7c41cc632d2bedab8ebbf4722e946cd))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>

### Continuous Integration

- Guard against stray uv.lock changes in PRs ([#351](https://github.com/posit-dev/vip/pull/351),
  [`028a2d5`](https://github.com/posit-dev/vip/commit/028a2d5b0bfcc6cf5783e36279c8e63cb6590f79))

- Make issue triage opt-in and add issue lifecycle labels
  ([#352](https://github.com/posit-dev/vip/pull/352),
  [`e87fd5b`](https://github.com/posit-dev/vip/commit/e87fd5b9e15057e6c400b5d5491ba29d9ff1967a))

### Documentation

- Plan for #344 — preserve line breaks in error_summary
  ([#345](https://github.com/posit-dev/vip/pull/345),
  [`1c40865`](https://github.com/posit-dev/vip/commit/1c40865056095dcf1d26907070f26effe051adf1))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.39.0 (2026-06-09)

### Chores

- **deps**: Bump the actions-dependencies group with 6 updates
  ([#340](https://github.com/posit-dev/vip/pull/340),
  [`09a59f5`](https://github.com/posit-dev/vip/commit/09a59f5b13341718b2929b43d18e5425942ccfdf))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump the python-dependencies group with 6 updates
  ([#339](https://github.com/posit-dev/vip/pull/339),
  [`33a1b71`](https://github.com/posit-dev/vip/commit/33a1b71d404d0c451e39063d54b112a62e65877f))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: Brian Deitte <brian.deitte@posit.co>

### Continuous Integration

- Add path filters to ci, preview, and website-preview workflows
  ([#337](https://github.com/posit-dev/vip/pull/337),
  [`a0c437f`](https://github.com/posit-dev/vip/commit/a0c437fb3db1fea16d8320232983ba8c31194d61))

- Run Connect tests using with-connect ([#338](https://github.com/posit-dev/vip/pull/338),
  [`b8730a1`](https://github.com/posit-dev/vip/commit/b8730a1c344fca2505a4ab888359140c427e7f54))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>

Co-authored-by: Brian Deitte <brian.deitte@posit.co>

- Smoke test updates, including running against the latest version
  ([#341](https://github.com/posit-dev/vip/pull/341),
  [`c91db13`](https://github.com/posit-dev/vip/commit/c91db13ee7eef23379ff79bdf763b969d029b34c))

### Documentation

- Plan for #301 — add in-session execution primitives for Workbench
  ([#317](https://github.com/posit-dev/vip/pull/317),
  [`4c33e7f`](https://github.com/posit-dev/vip/commit/4c33e7fe7025fb558ae3c2bb86acba99a2061df9))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>

- Plan for #306 — cover Git operations from Workbench sessions
  ([#309](https://github.com/posit-dev/vip/pull/309),
  [`77922c3`](https://github.com/posit-dev/vip/commit/77922c31c3231846cad6a24898abe68fdd560055))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>

### Features

- **workbench**: Add in-session execution primitives (closes #301)
  ([#349](https://github.com/posit-dev/vip/pull/349),
  [`3b336eb`](https://github.com/posit-dev/vip/commit/3b336eb88130592a7d509963b6ed8539bc9ce4b7))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <18703558+ian-flores@users.noreply.github.com>


## v0.38.0 (2026-06-02)

### Features

- **workbench**: Add Kubernetes autoscaling and capacity probes (closes #304)
  ([#334](https://github.com/posit-dev/vip/pull/334),
  [`b0c846d`](https://github.com/posit-dev/vip/commit/b0c846d8aa851bbd521b6b8b1c5b5c43ed9b530c))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>


## v0.37.0 (2026-06-02)

### Continuous Integration

- Add network allowlist for preview screenshot gallery
  ([#326](https://github.com/posit-dev/vip/pull/326),
  [`903a472`](https://github.com/posit-dev/vip/commit/903a472f826cf215b43f5a458ff98243e7df4121))

- **issue-triage**: Remove re-triage via remove_labels safe-output
  ([#331](https://github.com/posit-dev/vip/pull/331),
  [`e097859`](https://github.com/posit-dev/vip/commit/e0978595f603790555d90291c55cf62cb122866b))

### Documentation

- Plan for #302 — workbench jobs coverage ([#316](https://github.com/posit-dev/vip/pull/316),
  [`7081d5b`](https://github.com/posit-dev/vip/commit/7081d5beed591e8a5b61a23ec36ca9c25d80bd6e))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>

- Plan for #304 — add Kubernetes autoscaling and capacity probes
  ([#311](https://github.com/posit-dev/vip/pull/311),
  [`40f01cd`](https://github.com/posit-dev/vip/commit/40f01cd4ecaa689c6133394286d4b83eb1a17b02))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>

### Features

- **workbench**: Add Background Job and Workbench Job test coverage (closes #302)
  ([#336](https://github.com/posit-dev/vip/pull/336),
  [`9a9de55`](https://github.com/posit-dev/vip/commit/9a9de55856573c17731ae0c01d7d4c652d215485))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>


## v0.36.7 (2026-06-01)

### Bug Fixes

- **implement-plan**: Stop the agent inventing a placeholder PR number
  ([#329](https://github.com/posit-dev/vip/pull/329),
  [`e23bd75`](https://github.com/posit-dev/vip/commit/e23bd75b8db765bb8eebd20ded0d2e3731f8f11c))


## v0.36.6 (2026-06-01)

### Bug Fixes

- **issue-triage**: Allow cd and unmask re-triage label removal
  ([#328](https://github.com/posit-dev/vip/pull/328),
  [`9b8a53d`](https://github.com/posit-dev/vip/commit/9b8a53d8aa3fad4f3d638cce9438f0dd872da6da))

### Documentation

- Plan for #303 — verify expected R/Python versions on Workbench
  ([#314](https://github.com/posit-dev/vip/pull/314),
  [`c900ef3`](https://github.com/posit-dev/vip/commit/c900ef3d9168f903c027b54f143c7aa31a3abff4))

Co-authored-by: posit-vip-triage[bot] <288714212+posit-vip-triage[bot]@users.noreply.github.com>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>


## v0.36.5 (2026-06-01)

### Bug Fixes

- **workflows**: Force re-triage cleanup + pin agent models
  ([#323](https://github.com/posit-dev/vip/pull/323),
  [`790fb86`](https://github.com/posit-dev/vip/commit/790fb86509bf45872fe82922762b76740ce18e68))

### Continuous Integration

- **example-report**: Free disk space before image pulls
  ([#324](https://github.com/posit-dev/vip/pull/324),
  [`4f287d7`](https://github.com/posit-dev/vip/commit/4f287d76600f603ed2b9c2c2eb9d061449764a16))


## v0.36.4 (2026-05-31)

### Bug Fixes

- **connect**: Stop data-source step being collected as a stray test
  ([#322](https://github.com/posit-dev/vip/pull/322),
  [`173ca90`](https://github.com/posit-dev/vip/commit/173ca90142ed236a057191abf1610f23466d491a))


## v0.36.3 (2026-05-29)

### Bug Fixes

- **workbench**: Fail fast when a session reaches a terminal state
  ([#320](https://github.com/posit-dev/vip/pull/320),
  [`1f9e5ec`](https://github.com/posit-dev/vip/commit/1f9e5ecd1d44e11e5c6d0df871d44a4388e26379))


## v0.36.2 (2026-05-29)

### Bug Fixes

- **connect**: Reliably clean up VIP content on test failure
  ([#318](https://github.com/posit-dev/vip/pull/318),
  [`dfd8509`](https://github.com/posit-dev/vip/commit/dfd85095f5d8b5613c55097d2046289b58de01e6))


## v0.36.1 (2026-05-29)

### Bug Fixes

- **workbench**: Reliably clean up VIP sessions on test failure
  ([#312](https://github.com/posit-dev/vip/pull/312),
  [`2988129`](https://github.com/posit-dev/vip/commit/29881294b423d5deb37b9655a2833e8458c8e80e))


## v0.36.0 (2026-05-29)

### Features

- **cli**: Support help flag before the subcommand
  ([#297](https://github.com/posit-dev/vip/pull/297),
  [`9c0f1d5`](https://github.com/posit-dev/vip/commit/9c0f1d52f224c3df1d969c359382d57aea0cc8ac))


## v0.35.2 (2026-05-29)

### Bug Fixes

- **install**: Treat empty .vip-install.json as missing (closes #283)
  ([#296](https://github.com/posit-dev/vip/pull/296),
  [`e635796`](https://github.com/posit-dev/vip/commit/e6357967d99169c4cbed507a7b5e3001c0a37b57))

### Chores

- Authenticate agentic workflows via GitHub App ([#294](https://github.com/posit-dev/vip/pull/294),
  [`a8304ce`](https://github.com/posit-dev/vip/commit/a8304cedd10008491d6590405a79f736788915b2))

- **deps**: Bump github/gh-aw from 0.73.0 to 0.74.4 in the actions-dependencies group
  ([#285](https://github.com/posit-dev/vip/pull/285),
  [`416c198`](https://github.com/posit-dev/vip/commit/416c198de0fb2a02075f8110da5d8c7be474000b))

- **deps**: Bump the python-dependencies group with 8 updates
  ([#284](https://github.com/posit-dev/vip/pull/284),
  [`491b5d7`](https://github.com/posit-dev/vip/commit/491b5d73186de085ba3d36be7f5178aa5a68b7b5))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

Co-authored-by: Brian Deitte <brian.deitte@posit.co>

### Continuous Integration

- Narrow agentic workflow permissions to match the App's grants
  ([#295](https://github.com/posit-dev/vip/pull/295),
  [`88470d9`](https://github.com/posit-dev/vip/commit/88470d98de3a7b5583a3943d3be7c14554800302))


## v0.35.1 (2026-05-28)

### Bug Fixes

- **issue-triage**: Promote pre-run cleanup to dedicated Step 1a
  ([#293](https://github.com/posit-dev/vip/pull/293),
  [`61a82da`](https://github.com/posit-dev/vip/commit/61a82da347b55b7e961439b1b6aadd781591a0c2))

### Chores

- Add github issue templates for bugs and feature requests
  ([#289](https://github.com/posit-dev/vip/pull/289),
  [`818e47a`](https://github.com/posit-dev/vip/commit/818e47a15ec81bc5bce0b0a18da08744e7b89d2b))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

- Bootstrap thoughts/shared/plans/ for triage agent
  ([#290](https://github.com/posit-dev/vip/pull/290),
  [`26d8c26`](https://github.com/posit-dev/vip/commit/26d8c26bb4f13e9fba88b9f6c26ef37300ee3e62))


## v0.35.0 (2026-05-26)

### Features

- Add agentic issue triage workflows ([#281](https://github.com/posit-dev/vip/pull/281),
  [`0175728`](https://github.com/posit-dev/vip/commit/01757280e55589b7ac084e76436dbe809ba6a12d))


## v0.34.1 (2026-05-22)

### Bug Fixes

- **auth**: Surface workbench auth failures and scope cache per URL
  ([#279](https://github.com/posit-dev/vip/pull/279),
  [`f0479b7`](https://github.com/posit-dev/vip/commit/f0479b780a7c610bb6e53802b7a690436a2f7b01))

### Chores

- **deps**: Bump idna and starlette to fix CVEs ([#278](https://github.com/posit-dev/vip/pull/278),
  [`45a6ada`](https://github.com/posit-dev/vip/commit/45a6ada365ec6502fceb3424879bcc2cef72417c))


## v0.34.0 (2026-05-22)

### Chores

- **deps**: Bump the actions-dependencies group with 2 updates
  ([#272](https://github.com/posit-dev/vip/pull/272),
  [`ec1c51a`](https://github.com/posit-dev/vip/commit/ec1c51a0c140d388c9c1cee382348e98ecebfeee))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump the python-dependencies group with 6 updates
  ([#271](https://github.com/posit-dev/vip/pull/271),
  [`c53bc98`](https://github.com/posit-dev/vip/commit/c53bc988a3488b01a0f8ef34ad1b07dbdb3299bf))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Features

- **pm**: Add tests for authenticated repositories
  ([#270](https://github.com/posit-dev/vip/pull/270),
  [`fb8d28a`](https://github.com/posit-dev/vip/commit/fb8d28a2af65044e1c62cd78979d161c2a31168c))


## v0.33.1 (2026-05-18)

### Bug Fixes

- **auth**: Make headless-auth mint work on sub-path Connect URLs
  ([#262](https://github.com/posit-dev/vip/pull/262),
  [`89663ed`](https://github.com/posit-dev/vip/commit/89663edd01636f25ecce54970fea953f817c7150))


## v0.33.0 (2026-05-18)

### Bug Fixes

- **install**: Detect stale chromium cache via pinned revision
  ([#261](https://github.com/posit-dev/vip/pull/261),
  [`1fd9086`](https://github.com/posit-dev/vip/commit/1fd90862263254080a613e78fe0802546fba243a))

### Chores

- **deps**: Bump the actions-dependencies group across 1 directory with 8 updates
  ([#246](https://github.com/posit-dev/vip/pull/246),
  [`29166dc`](https://github.com/posit-dev/vip/commit/29166dc6ec8b72ac502bfdf1790da76127f4ab21))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump the python-dependencies group with 5 updates
  ([#260](https://github.com/posit-dev/vip/pull/260),
  [`5bc9a6e`](https://github.com/posit-dev/vip/commit/5bc9a6e3f67b6e4497d89f11c084e54e27ff3d01))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Features

- Add VIP_TEST_TOTP_SECRET for unattended --headless-auth MFA
  ([#267](https://github.com/posit-dev/vip/pull/267),
  [`bc7c746`](https://github.com/posit-dev/vip/commit/bc7c746bc0881092208911fa4550712b8cd26433))


## v0.32.1 (2026-05-13)

### Bug Fixes

- **workbench**: Resume sessions via Launch modal button
  ([#259](https://github.com/posit-dev/vip/pull/259),
  [`66067cc`](https://github.com/posit-dev/vip/commit/66067cc3938b0f7f93dc542545bc4a9c42b81a46))


## v0.32.0 (2026-05-12)

### Features

- **plugin**: Add --api-auth flag to run only API-key tests
  ([#253](https://github.com/posit-dev/vip/pull/253),
  [`4528b26`](https://github.com/posit-dev/vip/commit/4528b268bdf427f1f2a69f9e2cc9bafe711799c4))

Co-authored-by: Claude Opus 4.6 <noreply@anthropic.com>


## v0.31.2 (2026-05-12)

### Bug Fixes

- **workbench**: Run login form test under --headless-auth
  ([#258](https://github.com/posit-dev/vip/pull/258),
  [`d691353`](https://github.com/posit-dev/vip/commit/d691353497c5d9ca2d58b4bc8528a8eeee35751f))


## v0.31.1 (2026-05-12)

### Bug Fixes

- **config**: Redact secrets in config dataclass repr
  ([#257](https://github.com/posit-dev/vip/pull/257),
  [`d5fa5a9`](https://github.com/posit-dev/vip/commit/d5fa5a9b5d62d4e72f8b061c2c01cf795c57e208))


## v0.31.0 (2026-05-11)

### Chores

- **deps**: Bump urllib3 to fix CVE-2026-44431 and CVE-2026-44432
  ([#256](https://github.com/posit-dev/vip/pull/256),
  [`d6449f9`](https://github.com/posit-dev/vip/commit/d6449f9875cc695519fdfa517de42406f471207d))

### Features

- Validate IDE extension installation ([#161](https://github.com/posit-dev/vip/pull/161),
  [`2805a9c`](https://github.com/posit-dev/vip/commit/2805a9ccdcffec290174c2b804a6b46c40d2f207))

Co-authored-by: Ian Flores Siaca <iflores.siaca@posit.co>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>


## v0.30.1 (2026-05-11)

### Bug Fixes

- **install**: Use libasound2t64 on Ubuntu 24.04+
  ([#252](https://github.com/posit-dev/vip/pull/252),
  [`36b43d2`](https://github.com/posit-dev/vip/commit/36b43d206cb1302d0aed37c0356cef96f03fb500))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: ian-flores <18703558+ian-flores@users.noreply.github.com>


## v0.30.0 (2026-05-10)

### Features

- Better platform support along with CI and docs ([#250](https://github.com/posit-dev/vip/pull/250),
  [`7b2de30`](https://github.com/posit-dev/vip/commit/7b2de3023455435818afd75aa6e95a313cd55436))


## v0.29.1 (2026-05-08)

### Bug Fixes

- **auth**: Honor --insecure during Connect API key minting
  ([#248](https://github.com/posit-dev/vip/pull/248),
  [`b48f961`](https://github.com/posit-dev/vip/commit/b48f96125e0b6d1271d1f26da937cd9d82749e76))

- **insecure**: Honor TLS config across clients and step modules
  ([#247](https://github.com/posit-dev/vip/pull/247),
  [`d5bafb0`](https://github.com/posit-dev/vip/commit/d5bafb00aa1a263f005614d8e217a39dc9c1bd8b))

### Chores

- **deps**: Bump jupyter packages for CVE fixes ([#243](https://github.com/posit-dev/vip/pull/243),
  [`2d72710`](https://github.com/posit-dev/vip/commit/2d7271010f817e7731a0132952700eabd4f6a784))

- **deps**: Bump mako and mistune to fix CVEs ([#249](https://github.com/posit-dev/vip/pull/249),
  [`7d47e6d`](https://github.com/posit-dev/vip/commit/7d47e6d7a699ebf03195d3c57b4cae931bd2805b))

- **deps**: Bump the python-dependencies group with 5 updates
  ([#245](https://github.com/posit-dev/vip/pull/245),
  [`ecffd5f`](https://github.com/posit-dev/vip/commit/ecffd5f941300feabc6e1835be013e69ea75937d))

### Continuous Integration

- Harden checkouts with persist-credentials: false
  ([#244](https://github.com/posit-dev/vip/pull/244),
  [`2e03914`](https://github.com/posit-dev/vip/commit/2e0391483a1405b298ff329640c58160c1604cc7))

- Pin actions to SHAs and enforce with zizmor ([#242](https://github.com/posit-dev/vip/pull/242),
  [`1704c91`](https://github.com/posit-dev/vip/commit/1704c91a65b73b5f9623880f5070771ae3d164aa))


## v0.29.0 (2026-05-01)

### Chores

- **deps**: Bump the actions-dependencies group across 1 directory with 3 updates
  ([#230](https://github.com/posit-dev/vip/pull/230),
  [`a4cec4f`](https://github.com/posit-dev/vip/commit/a4cec4ff0e3ac387922d30705ac14a44b91e3967))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump the python-dependencies group across 1 directory with 4 updates
  ([#229](https://github.com/posit-dev/vip/pull/229),
  [`84d1ce5`](https://github.com/posit-dev/vip/commit/84d1ce54f4fb596430ebd115ac88f5b10a46c1cb))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Features

- Add install and uninstall commands, including RHEL support
  ([#241](https://github.com/posit-dev/vip/pull/241),
  [`073e22a`](https://github.com/posit-dev/vip/commit/073e22acfd02443006f2bb35ad2fb0c67a320176))


## v0.28.0 (2026-04-30)

### Features

- **plugin**: Make performance tests opt-in via --performance-tests
  ([#231](https://github.com/posit-dev/vip/pull/231),
  [`4a8ba2e`](https://github.com/posit-dev/vip/commit/4a8ba2e50aad66c8b09eceb82afcb13ce637e941))


## v0.27.0 (2026-04-30)

### Bug Fixes

- **app**: Seed results.json on first run and stop pre-run unlink
  ([#233](https://github.com/posit-dev/vip/pull/233),
  [`59b29f0`](https://github.com/posit-dev/vip/commit/59b29f09deb88f89c9f882d22cac1e4354dd567f))

### Features

- **cli**: Add --insecure and --ca-bundle for self-signed CAs
  ([#232](https://github.com/posit-dev/vip/pull/232),
  [`9959204`](https://github.com/posit-dev/vip/commit/9959204c4a7b84d1278609f3e5f7d10fb53f1633))


## v0.26.8 (2026-04-30)

### Bug Fixes

- **deps**: Pin pip>=26.1 for CVE-2026-3219 ([#234](https://github.com/posit-dev/vip/pull/234),
  [`275abd4`](https://github.com/posit-dev/vip/commit/275abd4954059c685d4522254a66e3ad5789a7ad))

### Chores

- Update gitignore ([#225](https://github.com/posit-dev/vip/pull/225),
  [`302bdea`](https://github.com/posit-dev/vip/commit/302bdeacbfd4a124b61df4e287d540f0707cfc4f))


## v0.26.7 (2026-04-24)

### Bug Fixes

- **docs**: Use venv in quick start instructions in README
  ([#221](https://github.com/posit-dev/vip/pull/221),
  [`0d93b74`](https://github.com/posit-dev/vip/commit/0d93b7431782ae0eef4a629027131170f6a6d836))

### Chores

- **deps**: Bump the actions-dependencies group with 4 updates
  ([#219](https://github.com/posit-dev/vip/pull/219),
  [`7d7e1d2`](https://github.com/posit-dev/vip/commit/7d7e1d2f08afd9795298622079cb605662b2b012))


## v0.26.6 (2026-04-22)

### Bug Fixes

- **workbench**: Disambiguate IDE session names under xdist
  ([#220](https://github.com/posit-dev/vip/pull/220),
  [`950cec8`](https://github.com/posit-dev/vip/commit/950cec83bb41a7f96ae65dd434058dfbc6fcb46d))


## v0.26.5 (2026-04-22)

### Bug Fixes

- **connect**: Declare rmarkdown closure and raise deploy timeout
  ([#218](https://github.com/posit-dev/vip/pull/218),
  [`c006838`](https://github.com/posit-dev/vip/commit/c006838a581de5bb6bf99e544c4863da1922abc1))


## v0.26.4 (2026-04-22)

### Bug Fixes

- **connect**: Resolve relative Location headers on redirect
  ([#216](https://github.com/posit-dev/vip/pull/216),
  [`7a163e5`](https://github.com/posit-dev/vip/commit/7a163e58675d9b42595e14b120120e2d25a8e678))


## v0.26.3 (2026-04-22)

### Bug Fixes

- **output**: Small fixup for output and docs ([#217](https://github.com/posit-dev/vip/pull/217),
  [`15ff959`](https://github.com/posit-dev/vip/commit/15ff959eabef0b1fb7c0d4aa4d311f61915f1d86))


## v0.26.2 (2026-04-22)

### Bug Fixes

- **connect**: Correct rmd, jupyter, and shiny content bundles
  ([#207](https://github.com/posit-dev/vip/pull/207),
  [`bf4854f`](https://github.com/posit-dev/vip/commit/bf4854f9aa1e355dc94ac3d1787b951dec8f68b9))

- **performance**: Skip on proxy errors and enforce PM token guard
  ([#209](https://github.com/posit-dev/vip/pull/209),
  [`d709c2b`](https://github.com/posit-dev/vip/commit/d709c2b66fd8337a3fc4a7c48805ffceec4d9113))

- **security**: Skip with clear diagnostic on TLS cert verify failure
  ([#210](https://github.com/posit-dev/vip/pull/210),
  [`0da623e`](https://github.com/posit-dev/vip/commit/0da623ed070aa394a5ffe01e491a3168f19c2e3f))

- **workbench**: Skip IDE tests gracefully when IDE is unavailable
  ([#208](https://github.com/posit-dev/vip/pull/208),
  [`f51b6f6`](https://github.com/posit-dev/vip/commit/f51b6f6ca6ecca28c8413b17561407e42c2bedb5))


## v0.26.1 (2026-04-22)

### Bug Fixes

- **deps**: Pin nbconvert>=7.17.1 for CVE-2026-39377/39378
  ([#212](https://github.com/posit-dev/vip/pull/212),
  [`1823e9a`](https://github.com/posit-dev/vip/commit/1823e9af4006f2a3b598a2acfadedcca15879654))


## v0.26.0 (2026-04-21)

### Features

- **plugin**: Enable pytest-xdist parallel execution without breaking report generation
  ([#205](https://github.com/posit-dev/vip/pull/205),
  [`440a0b3`](https://github.com/posit-dev/vip/commit/440a0b37bfd78ff020e799618d859c8c21f48aa1))


## v0.25.0 (2026-04-21)

### Bug Fixes

- **connect**: Short-circuit login form fill when using interactive auth
  ([#202](https://github.com/posit-dev/vip/pull/202),
  [`7578e6c`](https://github.com/posit-dev/vip/commit/7578e6c3019a99c516ff8ef55370e0de5435257b))

- **workbench**: Skip gracefully when IDE not installed instead of opaque error
  ([#203](https://github.com/posit-dev/vip/pull/203),
  [`245e394`](https://github.com/posit-dev/vip/commit/245e39470daf4ef4898e7f61f3c3da46b3b8c0f8))

- **workbench**: Skip gracefully when session suspend/resume not supported
  ([#204](https://github.com/posit-dev/vip/pull/204),
  [`0810284`](https://github.com/posit-dev/vip/commit/08102849e08893f4ac1454e2bbe2a32c417a7e38))

### Features

- Add local docker-compose environment for Playwright test development
  ([#206](https://github.com/posit-dev/vip/pull/206),
  [`0891335`](https://github.com/posit-dev/vip/commit/0891335819a78776aa81ad97c70d064dbe34d5e2))


## v0.24.10 (2026-04-21)

### Bug Fixes

- **ssl**: Tls verification test fails with unclear error behind SSL-terminating proxy
  ([#198](https://github.com/posit-dev/vip/pull/198),
  [`c057b80`](https://github.com/posit-dev/vip/commit/c057b805f48484bc0da10339edb4a8dc56ab42a1))


## v0.24.9 (2026-04-21)

### Bug Fixes

- **auth**: Fix a number of auth test issues recently discovered
  ([#201](https://github.com/posit-dev/vip/pull/201),
  [`ec5882c`](https://github.com/posit-dev/vip/commit/ec5882cbfb57089d38b790de4b35a1c02300a7f8))

### Chores

- **deps**: Bump the python-dependencies group across 1 directory with 4 updates
  ([#200](https://github.com/posit-dev/vip/pull/200),
  [`481f2c7`](https://github.com/posit-dev/vip/commit/481f2c7287047b65d7949b1e534e913fbb2ae12f))

### Continuous Integration

- **report**: Guard Quarto render against remaining hang causes
  ([#197](https://github.com/posit-dev/vip/pull/197),
  [`ad7b6c6`](https://github.com/posit-dev/vip/commit/ad7b6c6ddc57835f272a0de2d2e31315000efb07))


## v0.24.8 (2026-04-20)

### Bug Fixes

- **config**: Normalize product URLs — trailing slash for sub-path URLs only
  ([#188](https://github.com/posit-dev/vip/pull/188),
  [`7f7a1d1`](https://github.com/posit-dev/vip/commit/7f7a1d1df2508b976f78a5e31201c78b0fe47e64))

### Continuous Integration

- Remove showboat from GHA workflows ([#199](https://github.com/posit-dev/vip/pull/199),
  [`aea18d6`](https://github.com/posit-dev/vip/commit/aea18d6a20875e4860c19261b4a378b15e6d4ef1))


## v0.24.7 (2026-04-18)

### Bug Fixes

- **cli**: Always pass absolute --vip-config to pytest
  ([#194](https://github.com/posit-dev/vip/pull/194),
  [`93d0eb4`](https://github.com/posit-dev/vip/commit/93d0eb4969974fcbe32decb5d5b36f1f694260af))


## v0.24.6 (2026-04-18)

### Bug Fixes

- **security**: Move config hygiene tests to opt-in category
  ([#195](https://github.com/posit-dev/vip/pull/195),
  [`aea86af`](https://github.com/posit-dev/vip/commit/aea86af33e42cfdb9c0199bc881a899e126e511a))

### Continuous Integration

- **report**: Prevent Quarto render from hanging in example report job
  ([#196](https://github.com/posit-dev/vip/pull/196),
  [`5206402`](https://github.com/posit-dev/vip/commit/5206402c2116084b81effe38040b15e8c057d482))

### Refactoring

- **cli**: Share DEFAULT_TEST_TIMEOUT_SECONDS and fix TOML help wording
  ([#192](https://github.com/posit-dev/vip/pull/192),
  [`bde0a11`](https://github.com/posit-dev/vip/commit/bde0a11501c3a11f15546e5ec9e1ee8079f5681a))


## v0.24.5 (2026-04-18)

### Bug Fixes

- **auth**: Skip headless auth when no auth-requiring products configured
  ([#193](https://github.com/posit-dev/vip/pull/193),
  [`f330e13`](https://github.com/posit-dev/vip/commit/f330e13f2e8a601c3d270c26a0aab85079150c7c))

Co-authored-by: Claude <noreply@anthropic.com>

### Chores

- **deps**: Bump github/gh-aw-actions from 0.67.1 to 0.67.3 in the actions-dependencies group
  ([#164](https://github.com/posit-dev/vip/pull/164),
  [`9c141eb`](https://github.com/posit-dev/vip/commit/9c141eb1ed0cc92fd6e9a77f309cabc1eeb701ea))


## v0.24.4 (2026-04-18)

### Bug Fixes

- **cli**: Raise default --test-timeout to 3600s for Connect deploys
  ([#191](https://github.com/posit-dev/vip/pull/191),
  [`15b1c3e`](https://github.com/posit-dev/vip/commit/15b1c3e9a2c568a1f451bcf863032c89599f7092))


## v0.24.3 (2026-04-18)

### Bug Fixes

- **performance**: Update locust install instructions to use uv
  ([#190](https://github.com/posit-dev/vip/pull/190),
  [`58614ab`](https://github.com/posit-dev/vip/commit/58614abb8192c932607b81963bfe3d64cec1edba))


## v0.24.2 (2026-04-18)

### Bug Fixes

- **security**: Catch ConnectError with helpful skip message
  ([#189](https://github.com/posit-dev/vip/pull/189),
  [`c5dc180`](https://github.com/posit-dev/vip/commit/c5dc180695712d16ccf724f436de68fdc77a9fb0))


## v0.24.1 (2026-04-17)

### Bug Fixes

- Remove warnings when running from install ([#168](https://github.com/posit-dev/vip/pull/168),
  [`b5b5f09`](https://github.com/posit-dev/vip/commit/b5b5f093dccc553753d31fe716fe4fe346e610ba))


## v0.24.0 (2026-04-17)

### Features

- Headless auth support ([#166](https://github.com/posit-dev/vip/pull/166),
  [`8ed0997`](https://github.com/posit-dev/vip/commit/8ed0997ae7d9333c6a2dc15cd70424e562f3991a))


## v0.23.0 (2026-04-17)

### Features

- Auth and PPM load testing usability ([#165](https://github.com/posit-dev/vip/pull/165),
  [`b8159ce`](https://github.com/posit-dev/vip/commit/b8159ce072ac004c18cee63320e1b860dc5e8b63))


## v0.22.0 (2026-04-15)

### Features

- Usability improvements and new command-line options
  ([#162](https://github.com/posit-dev/vip/pull/162),
  [`7a850a4`](https://github.com/posit-dev/vip/commit/7a850a4270b2dbbed30e15e2cb2041c9bf383e14))


## v0.21.1 (2026-04-10)

### Bug Fixes

- **connect**: Use correct /v1/system/checks API for system checks
  ([#157](https://github.com/posit-dev/vip/pull/157),
  [`95438cc`](https://github.com/posit-dev/vip/commit/95438cc83f993e4d0d8663d26d1a2e815c7745c9))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>

### Chores

- **deps**: Bump the actions-dependencies group across 1 directory with 3 updates
  ([#156](https://github.com/posit-dev/vip/pull/156),
  [`912ae6b`](https://github.com/posit-dev/vip/commit/912ae6b7de0764a3c147be3b0d2b03c78a43426c))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump the python-dependencies group across 1 directory with 6 updates
  ([#155](https://github.com/posit-dev/vip/pull/155),
  [`969859e`](https://github.com/posit-dev/vip/commit/969859e26a0cdb743d2e863225d8300df597b4d5))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>


## v0.21.0 (2026-04-10)

### Documentation

- Reorder presentation slides ([#146](https://github.com/posit-dev/vip/pull/146),
  [`8ec69e5`](https://github.com/posit-dev/vip/commit/8ec69e5134800731d46390ec905c7c652ac7581e))

### Features

- Package Manager updates: fix Bioconductor and add OpenVSX
  ([#153](https://github.com/posit-dev/vip/pull/153),
  [`7b9dd01`](https://github.com/posit-dev/vip/commit/7b9dd010c28ff74e411d30d26b7682180307fc91))


## v0.20.1 (2026-04-07)

### Bug Fixes

- Improve test robustness for interactive-auth and missing IDEs
  ([#139](https://github.com/posit-dev/vip/pull/139),
  [`6ddf8a7`](https://github.com/posit-dev/vip/commit/6ddf8a747c853fc8daa5f3d4ba72cc954c934fb4))

### Continuous Integration

- Add preview screenshot agentic workflow ([#136](https://github.com/posit-dev/vip/pull/136),
  [`c4d6b73`](https://github.com/posit-dev/vip/commit/c4d6b73346cc6d9f9377bc264dfa4fde7a5d6cc7))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

### Documentation

- Add SE overview presentation ([#137](https://github.com/posit-dev/vip/pull/137),
  [`d85bc0c`](https://github.com/posit-dev/vip/commit/d85bc0c5eb76b1ca072cec69620b11ec3684d5b1))


## v0.20.0 (2026-04-06)

### Features

- **connect**: Add system checks test (closes #74) ([#98](https://github.com/posit-dev/vip/pull/98),
  [`829322f`](https://github.com/posit-dev/vip/commit/829322f20e283a7863d9beea7474e47eaa39f0bd))

Co-authored-by: Claude <noreply@anthropic.com>

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <iflores.siaca@posit.co>


## v0.19.1 (2026-04-06)

### Bug Fixes

- Resolve CVE-2026-4539 by upgrading pygments to >=2.20.0
  ([#135](https://github.com/posit-dev/vip/pull/135),
  [`53ecd3e`](https://github.com/posit-dev/vip/commit/53ecd3e8c30b1b9fdf30258be8e00e6cbc18d415))

### Chores

- Add authors and alpha milestone summary ([#134](https://github.com/posit-dev/vip/pull/134),
  [`b877a9b`](https://github.com/posit-dev/vip/commit/b877a9bdf4017486804654e8ec9547bedfa56fe8))


## v0.19.0 (2026-04-06)

### Features

- Improve example report — fix troubleshooting, expand tests, better styling
  ([#133](https://github.com/posit-dev/vip/pull/133),
  [`3ee864f`](https://github.com/posit-dev/vip/commit/3ee864f46bb339f62d7266c6300cd2686bde37d2))


## v0.18.0 (2026-04-06)

### Features

- Add Workbench to example validation report ([#132](https://github.com/posit-dev/vip/pull/132),
  [`a4a852e`](https://github.com/posit-dev/vip/commit/a4a852efca3521f0de2a5ee11e73c709eef77914))


## v0.17.0 (2026-04-06)

### Features

- Migrate workbench smoke tests to with-workbench CLI and expand coverage
  ([#100](https://github.com/posit-dev/vip/pull/100),
  [`bc8b3cc`](https://github.com/posit-dev/vip/commit/bc8b3cc17bf92a04569e05f506d98dea012e5be2))


## v0.16.0 (2026-04-06)

### Features

- **workbench**: Add session capacity testing with resource profiles
  ([#128](https://github.com/posit-dev/vip/pull/128),
  [`dea5ccc`](https://github.com/posit-dev/vip/commit/dea5ccc6b89cac5f8949d2e523953403f754a3fb))


## v0.15.0 (2026-04-02)

### Features

- **performance**: Add logarithmic-scale load testing with pluggable engine
  ([#124](https://github.com/posit-dev/vip/pull/124),
  [`23730af`](https://github.com/posit-dev/vip/commit/23730af3c6d45f4ba74e15ed88d5081607b74173))


## v0.14.0 (2026-04-01)

### Features

- **performance**: Add concurrent user load tests for each product
  ([#118](https://github.com/posit-dev/vip/pull/118),
  [`f5f20e4`](https://github.com/posit-dev/vip/commit/f5f20e463e95c7a8d18e8a2037d5803abc0d9b3d))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <iflores.siaca@posit.co>

Co-authored-by: Elliot Murphy <statik@users.noreply.github.com>

Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>


## v0.13.2 (2026-04-01)

### Bug Fixes

- **example-report**: Skip Package Manager when RSPM_LICENSE is unavailable
  ([#116](https://github.com/posit-dev/vip/pull/116),
  [`34a6eba`](https://github.com/posit-dev/vip/commit/34a6eba92a83e1b4169db3091f9d2b69a3bc0f62))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

Co-authored-by: Ian Flores Siaca <iflores.siaca@posit.co>

### Documentation

- Polish documentation for alpha release ([#121](https://github.com/posit-dev/vip/pull/121),
  [`6592978`](https://github.com/posit-dev/vip/commit/659297859e86d7b32f7b098bdbf5a0f432a060e9))


## v0.13.1 (2026-04-01)

### Bug Fixes

- **deps**: Pin cryptography>=46.0.6 for CVE-2026-34073
  ([#123](https://github.com/posit-dev/vip/pull/123),
  [`7360a4d`](https://github.com/posit-dev/vip/commit/7360a4d5771b58ad2196826f27628431cc496ac5))


## v0.13.0 (2026-03-27)

### Features

- Add feature matrix page to website ([#120](https://github.com/posit-dev/vip/pull/120),
  [`c8b4a2f`](https://github.com/posit-dev/vip/commit/c8b4a2fb19cd97ea3125a8c17dafae4905a52916))


## v0.12.2 (2026-03-26)

### Bug Fixes

- Include tests/ directory in the package wheel ([#110](https://github.com/posit-dev/vip/pull/110),
  [`bf23266`](https://github.com/posit-dev/vip/commit/bf232662ede07d481f4e658d9682ef3679907ce1))

### Chores

- **deps**: Bump requests from 2.32.5 to 2.33.0 ([#114](https://github.com/posit-dev/vip/pull/114),
  [`d3a118b`](https://github.com/posit-dev/vip/commit/d3a118bbc39aa736636b457abe022a0e2322d5a6))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

- **deps**: Bump the actions-dependencies group with 4 updates
  ([#112](https://github.com/posit-dev/vip/pull/112),
  [`653be07`](https://github.com/posit-dev/vip/commit/653be07797f88c97c491525c46b696ecc1e0833d))

- **deps**: Bump the python-dependencies group with 4 updates
  ([#111](https://github.com/posit-dev/vip/pull/111),
  [`90ca94f`](https://github.com/posit-dev/vip/commit/90ca94f4f61586d6e36ef998041d5c5db97b6d97))

### Documentation

- Update install instructions to use PyPI ([#104](https://github.com/posit-dev/vip/pull/104),
  [`c5b576f`](https://github.com/posit-dev/vip/commit/c5b576f74f43a653ed12ad6fa12f6b2e1139731c))


## v0.12.1 (2026-03-24)

### Bug Fixes

- **ci**: Rename package to posit-vip to match PyPI project
  ([#102](https://github.com/posit-dev/vip/pull/102),
  [`dc32200`](https://github.com/posit-dev/vip/commit/dc322002abbf49279e1a7f1a7e5ca1125260ebd4))


## v0.12.0 (2026-03-24)

### Features

- Add git-backed publishing test for Connect ([#99](https://github.com/posit-dev/vip/pull/99),
  [`ffd14a4`](https://github.com/posit-dev/vip/commit/ffd14a4f5ca87d3bb2e8e5f21c16265ff30587aa))


## v0.11.1 (2026-03-23)

### Bug Fixes

- **ci**: Trigger PyPI publish on tag push instead of release event
  ([#97](https://github.com/posit-dev/vip/pull/97),
  [`8704193`](https://github.com/posit-dev/vip/commit/87041934302c65b7bc8e44d36c3199ae83938614))


## v0.11.0 (2026-03-23)

### Features

- Add SessionStart hook to auto-install gh CLI ([#96](https://github.com/posit-dev/vip/pull/96),
  [`016fe67`](https://github.com/posit-dev/vip/commit/016fe67ac2fa239977d6fd9d27e6040a74ff0af7))


## v0.10.0 (2026-03-23)

### Chores

- **deps**: Bump boto3 from 1.42.63 to 1.42.65 in the python-dependencies group
  ([#89](https://github.com/posit-dev/vip/pull/89),
  [`1079c09`](https://github.com/posit-dev/vip/commit/1079c0932eb3ba639b14775cbac7299d6527f678))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

- **deps**: Bump the actions-dependencies group with 7 updates
  ([#90](https://github.com/posit-dev/vip/pull/90),
  [`1bd5984`](https://github.com/posit-dev/vip/commit/1bd5984c123148413d5f78578e6477fa90c94da9))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Continuous Integration

- Publish wheels to PyPI on GitHub releases ([#92](https://github.com/posit-dev/vip/pull/92),
  [`ac459a9`](https://github.com/posit-dev/vip/commit/ac459a92d9dc5464ee8488e2d7338a26b9a3f1a7))

### Documentation

- **website**: Update hero banner to say Posit Team
  ([#93](https://github.com/posit-dev/vip/pull/93),
  [`f6734fb`](https://github.com/posit-dev/vip/commit/f6734fbd350e96eb42cb2ad5af929881fb138973))

### Features

- Add four-layer test architecture guide and test-architect agent
  ([#95](https://github.com/posit-dev/vip/pull/95),
  [`28fcb53`](https://github.com/posit-dev/vip/commit/28fcb5342a668cbe5540087f61a66896f774ce9e))


## v0.9.2 (2026-03-17)

### Bug Fixes

- **website**: Fix copy buttons and reorder landing page
  ([#88](https://github.com/posit-dev/vip/pull/88),
  [`ad78fca`](https://github.com/posit-dev/vip/commit/ad78fca8bbdecb2871c3b2ced86834b073036f66))


## v0.9.1 (2026-03-16)

### Bug Fixes

- **website**: Reorganize landing page (#86) ([#87](https://github.com/posit-dev/vip/pull/87),
  [`208c65f`](https://github.com/posit-dev/vip/commit/208c65fd670cdb9f9d8cd7375282f5caa361d905))

### Refactoring

- Comprehensive codebase review — bugs, dedup, API design, features, CI
  ([#85](https://github.com/posit-dev/vip/pull/85),
  [`e7c34c2`](https://github.com/posit-dev/vip/commit/e7c34c2eb399759384a072ea9169535e310580ae))


## v0.9.0 (2026-03-14)

### Chores

- **deps**: Bump the python-dependencies group with 2 updates
  ([#63](https://github.com/posit-dev/vip/pull/63),
  [`4d03070`](https://github.com/posit-dev/vip/commit/4d03070e8947c8f41a2b1b2bf4242e298e618908))

Signed-off-by: dependabot[bot] <support@github.com>

Co-authored-by: dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>

### Features

- Add Shiny app for interactive test running ([#84](https://github.com/posit-dev/vip/pull/84),
  [`dd92337`](https://github.com/posit-dev/vip/commit/dd9233791044102c2a42035eccb37361a62e43d2))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>

### Testing

- **ci**: Add expected failure test for report preview
  ([#83](https://github.com/posit-dev/vip/pull/83),
  [`cbcf579`](https://github.com/posit-dev/vip/commit/cbcf5794caf82d669f05540e6a533aca842da017))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>


## v0.8.0 (2026-03-13)

### Features

- **website**: Add example validation report page ([#82](https://github.com/posit-dev/vip/pull/82),
  [`46153b1`](https://github.com/posit-dev/vip/commit/46153b1ce0404664bcc644f08e9e4bd175fb8de5))

Co-authored-by: Copilot Autofix powered by AI <175728472+Copilot@users.noreply.github.com>


## v0.7.0 (2026-03-13)

### Features

- **ci**: Add license error annotations to smoke test workflows
  ([#81](https://github.com/posit-dev/vip/pull/81),
  [`2100d25`](https://github.com/posit-dev/vip/commit/2100d25772e12796a99cec8c3a6233e73f4fe8ef))


## v0.6.1 (2026-03-13)

### Bug Fixes

- **ci**: Use matrix version in smoke test artifact names
  ([#80](https://github.com/posit-dev/vip/pull/80),
  [`2cd5113`](https://github.com/posit-dev/vip/commit/2cd5113f14b08bd6dba30bd5180b655e2553ed61))

### Documentation

- Section README into smaller focused documents ([#79](https://github.com/posit-dev/vip/pull/79),
  [`42ec96b`](https://github.com/posit-dev/vip/commit/42ec96bede101eb6d534d1423ca1bb188d017751))

Co-authored-by: copilot-swe-agent[bot] <198982749+Copilot@users.noreply.github.com>

Co-authored-by: statik <983+statik@users.noreply.github.com>

Co-authored-by: Elliot Murphy <statik@users.noreply.github.com>


## v0.6.0 (2026-03-12)

### Features

- **website**: Restyle site to align with Posit brand
  ([#77](https://github.com/posit-dev/vip/pull/77),
  [`4530266`](https://github.com/posit-dev/vip/commit/4530266ba2b7584864a1cc1ffa76c5d79c8bb4d9))


## v0.5.0 (2026-03-12)

### Features

- **website**: Simplify install and test run instructions
  ([#72](https://github.com/posit-dev/vip/pull/72),
  [`12b7e3a`](https://github.com/posit-dev/vip/commit/12b7e3a57e89230307e760d723c6980040b05b8c))


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
