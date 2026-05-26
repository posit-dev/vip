# Agentic workflows

VIP runs two GitHub-Actions agents that watch issues and propose work
for human review.

## Issue triage (`issue-triage.md`)

Fires on every newly opened issue (and on `re-triage`). The agent reads
the issue, decides whether it's a bug or an enhancement, and produces
one of three outputs:

- **Bug, fixable**: opens a pull request with the production fix, a
  selftest, and an auto-generated showboat demo.
- **Enhancement**: opens a pull request that adds a markdown plan to
  `thoughts/shared/plans/` and posts a summary comment on the issue.
  Merging the plan PR is the human's "approved — go implement" signal.
- **Can't proceed**: posts a structured comment explaining what's
  missing and labels the issue `needs-human-triage`.

## Plan implementation (`implement-plan.md`)

Fires when a pull request that touches `thoughts/shared/plans/**` is
merged. The agent reads the plan, applies it, and opens an
implementation PR.

## Labels the workflows use

| Label | Set by | Effect |
|---|---|---|
| `skip-triage` | maintainer, before issue is opened or any time | Triage workflow exits at the gate. |
| `triaged-by-bot` | bot, after every run | Subsequent triage runs are skipped unless `re-triage` is set. |
| `needs-human-triage` | bot, on the can't-proceed path | Filter for issues the bot bounced. |
| `re-triage` | maintainer, manually | Forces another triage run; the bot removes the label after picking it up. |

## How to opt an issue out

Apply the `skip-triage` label. The workflow exits at the first step
without commenting.

## How to retry triage

Apply the `re-triage` label. The bot will run again and remove the
label.

## How to iterate on a plan before implementation fires

The implementation workflow only fires on **merge** of a plan PR. While
you're iterating on the plan PR, the implementer is dormant. Push
changes, review, comment — implementation only kicks off once the plan
PR is merged into `main`.

## Bot identity

PRs are authored by the `Copilot` identity (the same account that opens
the screenshot-gallery PRs from `preview-screenshot-gallery.md`). To
filter the bot's PRs in the GitHub UI, search for `author:app/copilot`.

## Source files

Both workflows are gh-aw agents:

- `.github/workflows/issue-triage.md` — source
- `.github/workflows/issue-triage.lock.yml` — compiled (do not hand-edit)
- `.github/workflows/implement-plan.md` — source
- `.github/workflows/implement-plan.lock.yml` — compiled (do not hand-edit)

To update either, edit the `.md` file and run `gh aw compile`.

## Scope guards

The bot is forbidden from modifying release machinery, CI workflows,
version pins, dependency manifests, or top-level config files. New
files can only be added under `selftests/`, `src/vip_tests/`,
`thoughts/shared/plans/`, or `validation_docs/`. See the "Scope guards"
section of `issue-triage.md` for the full list.
