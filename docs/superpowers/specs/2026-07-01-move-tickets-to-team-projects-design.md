# Move tickets to product team projects (issue #413)

## Problem

Issue [#413](https://github.com/posit-dev/vip/issues/413): "Similar to the helm
project, move tickets to team projects." When a VIP issue concerns a specific
Posit product, a maintainer should be able to route it onto that product team's
org-level GitHub project board without leaving the vip repo.

This is a port of the helm project's
[`issues.yml`](https://github.com/rstudio/helm/blob/main/.github/workflows/issues.yml)
workflow, dropping the chronicle and launcher teams — VIP only covers Connect,
Workbench, and Package Manager.

## Solution overview

Add a GitHub Actions workflow that fires when an issue is labeled. If the label
is a recognized `team: <product>` label, the workflow adds the issue to that
product team's org-level project board using a GitHub App token that has
`organization-projects: write` on the target org.

## Components

### 1. Workflow: `.github/workflows/add-to-team-project.yml`

- **Trigger:** `issues:` with `types: [labeled]` only. No `pull_request` test
  trigger (helm keeps a commented-out one; we omit it entirely).
- **Top-level `permissions: {}`** — the project write is performed with an app
  token, not the default `GITHUB_TOKEN`, so no default scopes are needed.
- **Single job, three steps:**

  1. **Map label → project** (`id: project-url`). Branch on
     `github.event.label.name`:

     | Label                   | Project URL                                       | Org        |
     |-------------------------|---------------------------------------------------|------------|
     | `team: connect`         | `https://github.com/orgs/posit-dev/projects/23`   | `posit-dev`|
     | `team: workbench`       | `https://github.com/orgs/rstudio/projects/92`     | `rstudio`  |
     | `team: package manager` | `https://github.com/orgs/rstudio/projects/48`     | `rstudio`  |
     | anything else           | `PROJECT=none`                                     | —          |

     Emits `PROJECT` and `ORG` to `$GITHUB_OUTPUT`. Any non-team label yields
     `PROJECT=none`, which makes the remaining steps no-ops. Project URLs and
     orgs are carried over unchanged from helm (these boards are shared,
     org-level project boards, not repo-specific).

  2. **Generate token** (`actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1` — v3.2.0),
     guarded by `if: steps.project-url.outputs.project != 'none'`:
     - `app-id: ${{ secrets.POSIT_PLATFORM_APP_ID }}`
     - `private-key: ${{ secrets.POSIT_PLATFORM_PEM }}`
     - `owner: ${{ steps.project-url.outputs.ORG }}`
     - `permission-organization-projects: write`

  3. **Add issue to project** (`actions/add-to-project@5afcf98fcd03f1c2f92c3c83f58ae24323cc57fd` — v2.0.0),
     same `if:` guard:
     - `project-url: ${{ steps.project-url.outputs.PROJECT }}`
     - `github-token: ${{ steps.generate-token.outputs.token }}`
     - `labeled: ${{ github.event.label.name }}`

  Action pins match those already used elsewhere in this repo
  (`create-github-app-token` is pinned to the same SHA in
  `issue-triage.lock.yml`).

### 2. Repo labels

Create three labels in `posit-dev/vip`, matching helm's names, color, and
description style:

| Name                    | Color    | Description                            |
|-------------------------|----------|----------------------------------------|
| `team: connect`         | `BF4EEC` | Posit Connect related issue            |
| `team: workbench`       | `BF4EEC` | Posit Workbench related issue          |
| `team: package manager` | `BF4EEC` | Posit Package Manager related issue    |

Created via `gh label create` (idempotent with `--force`). The workflow only
does anything once one of these labels exists and is applied.

### 3. Docs

Add one row to the "CI workflows" list in `CLAUDE.md` describing
`add-to-team-project.yml`.

## Prerequisite (org-admin, outside this PR)

The workflow authenticates with the same cross-org GitHub App that helm uses.
For it to succeed at runtime:

- `POSIT_PLATFORM_APP_ID` and `POSIT_PLATFORM_PEM` secrets must be available to
  the `posit-dev/vip` repository (repo or org-level secrets).
- The underlying GitHub App must be installed on both the `posit-dev` and
  `rstudio` organizations with `organization-projects: write`.

These are org-admin steps that cannot be performed or verified from the repo, so
they are called out in the PR body rather than automated here.

## Non-goals

- No chronicle or launcher team routing (out of scope for VIP).
- No removal-from-board or label-removed handling — helm only adds on label add,
  and we match that.
- No changes to the existing triage app (`POSIT_VIP_TRIAGE_*`); that app is
  repo-scoped and is not expected to have cross-org project write.

## Verification

CI cannot write to the product boards, so end-to-end validation is a manual,
post-merge step. Automated/demoable checks:

- YAML / actionlint validity of the new workflow.
- The three `team: *` labels exist in the repo after creation.
- Workflow file contents (trigger, label→project mapping, pinned actions).

The true end-to-end check — apply `team: connect` to a test issue and confirm it
appears on the Connect board — is documented in the PR for a maintainer to run
once the secrets/app install are in place.
