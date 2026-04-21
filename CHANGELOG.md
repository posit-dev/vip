# CHANGELOG


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
