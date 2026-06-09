# Agentic workflows

VIP runs two GitHub-Actions agents that watch issues and propose work
for human review.

## Issue triage (`issue-triage.md`)

Triage is **opt-in**. The agent does nothing on its own — it fires only
when a maintainer applies the `needs-bot-triage` label to an issue,
explicitly handing it over. (Newly opened issues are ignored until
labeled.) The bot removes `needs-bot-triage` as soon as it picks the
issue up, so re-applying the label requests another pass.

Once triggered, the agent reads the issue, decides whether it's a bug or
an enhancement, and produces one of three outputs:

- **Bug, fixable**: opens a pull request with the production fix, a
  selftest, and an auto-generated showboat demo.
- **Enhancement**: opens a pull request that adds a markdown plan to
  `thoughts/shared/plans/`, posts a summary comment on the issue, and
  labels it `plan-pending-review`. Merging the plan PR is the human's
  "approved — go implement" signal.
- **Can't proceed**: posts a structured comment explaining what's
  missing and labels the issue `needs-human-triage`.

## Plan implementation (`implement-plan.md`)

Fires when a pull request that touches `thoughts/shared/plans/**` is
merged. The agent reads the plan, applies it, and opens an
implementation PR. As it starts, it swaps the originating issue's
`plan-pending-review` label for `implementing`. The issue closes
automatically when the implementation PR (which carries `Closes #<num>`)
merges.

It runs under a 30-minute budget and is instructed to ship the smallest
coherent slice — committing incrementally and, if it runs low on time,
opening a **draft** PR with a remaining-work checklist rather than
producing nothing.

## Issue label lifecycle

An issue moves through these states; the label tells you where it is at
a glance:

| Label | Set by | Means |
|---|---|---|
| *(none)* | — | Excluded — the bot ignores it until opted in. |
| `needs-bot-triage` | maintainer | Opt-in: run (or re-run) triage. Bot removes it on pickup. |
| `triaged-by-bot` | bot, after every run | Bot has examined the issue. |
| `plan-pending-review` | bot (enhancement path) | A plan PR is open and awaiting human review. |
| `implementing` | implement-plan, on plan merge | Plan merged; an implementation PR is in flight. |
| `needs-human-triage` | bot (can't-proceed path) | Bot couldn't propose an action; needs a maintainer. |
| `skip-triage` | maintainer | Hard opt-out; triage exits at the gate even if `needs-bot-triage` is added. |

## How to triage an issue

Apply the `needs-bot-triage` label. The bot picks it up, removes the
label, and runs. To request another pass later, re-apply it.

## How to keep the bot away from an issue

Leave it unlabeled (the default), or apply `skip-triage` to hard-block
triage even if someone later adds `needs-bot-triage`.

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
