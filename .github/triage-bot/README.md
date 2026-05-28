# VIP triage bot

This directory documents the two gh-aw workflows that triage open
issues on `posit-dev/vip`. The workflows themselves live in
`.github/workflows/`:

- `issue-triage.md` — fires on issue events
- `implement-plan.md` — fires when a plan PR is merged

## What the bot does

| Trigger | Action |
|---|---|
| Issue opened, no `skip-triage` label | Bot classifies as bug or enhancement, then either opens a PR (bug, high confidence), opens a plan PR (enhancement), or posts a needs-info comment. |
| Plan PR merged into `main` | Implementer agent reads the plan and opens an implementation PR. |
| `@Copilot retry` comment from a CODEOWNER | Re-runs triage on the issue. |

## Authentication

The workflows authenticate via a dedicated GitHub App scoped to
`posit-dev/vip`, rather than the default `GITHUB_TOKEN`. The org
blocks `GITHUB_TOKEN` from creating pull requests; rather than flip
that setting globally (which would also unblock every third-party
Action in the repo), the bot operates under a purpose-built App with
narrow permissions and a distinct audit trail.

### Required secrets

App credentials (provisioned by CloudOps):

- `POSIT_VIP_TRIAGE_CLIENT_ID` — App Client ID
- `POSIT_VIP_TRIAGE_PEM` — App private key (PEM-encoded)

Existing gh-aw infrastructure secrets remain configured:

- `COPILOT_GITHUB_TOKEN`
- `GH_AW_GITHUB_TOKEN`
- `GH_AW_GITHUB_MCP_SERVER_TOKEN`

At runtime, `actions/create-github-app-token` mints a short-lived
installation token from the App credentials. The compiled `.lock.yml`
files thread this token through both the agent's GitHub MCP calls
(`tools.github`) and the workflow's safe outputs (`add-comment`,
`add-labels`, `create-pull-request`).

### Required App permissions

The App needs these repository permissions on `posit-dev/vip`:

| Permission | Level | Used by |
|---|---|---|
| Contents | Read and write | Bot commits and branch pushes |
| Issues | Read and write | `gh issue view/edit/comment`, label management |
| Pull requests | Read and write | `safe-outputs.create-pull-request` |
| Metadata | Read | Default; always required |

It does not need access to any other repository.

### What happens if credentials are missing

If `POSIT_VIP_TRIAGE_CLIENT_ID` or `POSIT_VIP_TRIAGE_PEM` is unset,
the workflow will fail at the `actions/create-github-app-token` step
on first run. Both secrets are required.

## Compiling

After editing either `.md` source:

```bash
gh aw compile
```

This rewrites the corresponding `.lock.yml` next to the source. The
`.lock.yml` files are checked in. Do not edit them by hand.

## Labels

The triage workflow creates these on first run if they don't already
exist:

- `triaged-by-bot` — applied after every successful run
- `needs-human-triage` — applied when the bot can't propose action
- `skip-triage` — opt-out (set by humans)
- `re-triage` — re-run the agent (set by humans; the bot removes it
  after picking it up)

## Scope guards

The bot is forbidden from modifying release/CI machinery, version
pins, dependency manifests, and top-level config files. It can only
create new files under specific allowlisted directories. See the
"Scope guards" section of `.github/workflows/issue-triage.md` for the
full denylist and whitelist.

## Opting out of automation

Apply the `skip-triage` label to any issue you don't want the bot to
touch. The workflow exits at the gate without commenting.

## Re-triggering

Apply the `re-triage` label to an issue already marked
`triaged-by-bot`. The bot will run again and remove `re-triage`. Use
this after adding the missing info the bot asked for.

## Cost and quotas

Both workflows use `engine: copilot` and consume from the repository's
GitHub Copilot subscription. Monitor usage from the Copilot dashboard.
If volume becomes problematic, tighten the gate (for example, by
requiring an explicit `triage-me` label rather than running on every
open issue).
