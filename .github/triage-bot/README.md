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

The workflows use the same gh-aw secrets already configured for the
screenshot-gallery agent. No new provisioning is needed:

- `COPILOT_GITHUB_TOKEN`
- `GH_AW_GITHUB_TOKEN`
- `GH_AW_GITHUB_MCP_SERVER_TOKEN`

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
