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

## Required secrets

The workflows use the gh-aw secrets already configured for the
screenshot-gallery agent, plus one new secret that lets the bot create
pull requests when org policy blocks `GITHUB_TOKEN` from doing so:

- `COPILOT_GITHUB_TOKEN` (existing)
- `GH_AW_GITHUB_TOKEN` (existing)
- `GH_AW_GITHUB_MCP_SERVER_TOKEN` (existing)
- `TRIAGE_BOT_TOKEN` (new) — see below

### Setting up `TRIAGE_BOT_TOKEN`

`posit-dev` blocks GitHub Actions from creating pull requests at the
org level. Without an alternate token, the bot falls back to opening a
review-issue with a "Create PR" link instead of opening the PR
directly. To restore the direct-PR behavior, `TRIAGE_BOT_TOKEN` must
be set to a token that bypasses the org policy.

Two options:

1. **GitHub App (recommended)**: Create a dedicated GitHub App scoped
   to `posit-dev/vip` with `issues: write`, `pull-requests: write`,
   and `contents: write` repository permissions. Install it on the
   repo, then add a workflow step that uses
   `actions/create-github-app-token@v1` to mint an installation token
   each run. PRs are then authored by the App identity (e.g.,
   `vip-triage-bot[bot]`).

2. **Fine-grained PAT**: Create a fine-grained personal access token
   on a maintainer's account with `Pull requests: Read and write`,
   `Issues: Read and write`, and `Contents: Read and write` for
   `posit-dev/vip`. Store as `TRIAGE_BOT_TOKEN` repository secret.
   PRs are authored by the maintainer's identity. Simpler to set up
   but tied to one person; rotate when the PAT expires.

Until `TRIAGE_BOT_TOKEN` is configured, the bot continues to function
via the fallback (review-issue with a manual "Create PR" link),
matching gh-aw's default behavior.

## Required permissions

Declared per-workflow in the source `.md` frontmatter. Both workflows
need `issues: write`, `pull-requests: write`, and `contents: write`
at the job level so they can open PRs, comment, and apply labels.

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
