# CHANGELOG


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
