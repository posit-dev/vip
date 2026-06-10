---
on:
  pull_request:
    types: [closed]
    branches: [main]
    paths:
      - "thoughts/shared/plans/**.md"
timeout-minutes: 30
engine:
  id: copilot
  model: claude-sonnet-4.6
permissions:
  contents: read
  issues: read
  pull-requests: read
tools:
  github:
    toolsets: [default]
    github-app:
      client-id: ${{ secrets.POSIT_VIP_TRIAGE_CLIENT_ID }}
      private-key: ${{ secrets.POSIT_VIP_TRIAGE_PEM }}
  bash:
    - "gh issue view:*"
    - "gh issue comment:*"
    - "gh label create:*"
    - "gh pr view:*"
    - "gh pr comment:*"
    - "rg:*"
    - "grep:*"
    - "ls:*"
    - "cat:*"
    - "git diff:*"
    - "git status"
    - "git log:*"
    - "uv run:*"
    - "uvx showboat:*"
    - "just:*"
    - "npx commitlint:*"
safe-outputs:
  github-app:
    client-id: ${{ secrets.POSIT_VIP_TRIAGE_CLIENT_ID }}
    private-key: ${{ secrets.POSIT_VIP_TRIAGE_PEM }}
  add-comment:
    max: 2
    target: "*"
    discussions: false
  add-labels:
    max: 1
    target: "*"
    allowed: ["implementing"]
  remove-labels:
    max: 1
    target: "*"
    allowed: ["plan-pending-review"]
  create-pull-request:
    branch-prefix: "bot-"
    draft: false
    max: 1
network:
  allowed:
    - defaults
---

# Implement an approved plan PR

This workflow fires when a pull request that adds or modifies a file
under `thoughts/shared/plans/**` is **closed and merged**. It produces
an implementation pull request for the plan that just landed.

## Step 1 — gate

The PR number is `${{ github.event.pull_request.number }}`. Read the
PR details by running:

```bash
gh pr view ${{ github.event.pull_request.number }} \
  --json merged,mergedAt,mergeCommit,author,labels,baseRefName,files
```

Exit silently if **any** of:

- `.merged` is not `true` (PR was closed without merging).
- `.author.login` is not `Copilot` (the triage bot's identity) — i.e.,
  this PR was authored by a human, not the bot, and we should not
  auto-implement it.
- None of `.files[].path` are under `thoughts/shared/plans/`.

## Step 2 — find the plan and the originating issue

1. From the JSON above, take `.mergeCommit.oid` as the merge SHA, and
   the first entry of `.files[].path` matching `thoughts/shared/plans/`
   as the plan file.
2. Read the plan file. The first line of plan PRs created by the
   triage bot follows `# Plan for issue #<num>` — parse the issue
   number from there. If the plan file does not name an issue, comment
   on the PR with "Plan does not reference an issue number; cannot
   continue" and exit.

## Step 3 — implement

This workflow runs under a hard time budget (`timeout-minutes: 30`). A
previous run burned the entire budget and produced **nothing** — never
let that happen again. Work in the smallest shippable increments and
commit as you go, so progress is always preserved.

Read the plan in full. Then:

1. Make the code, test, and documentation changes that the plan
   specifies. The plan should be detailed enough that scope is
   unambiguous; if it is not, fall through to Step 5.
   - **Scope to one coherent surface per run.** If the plan spans
     several independent deliverables (e.g. multiple IDEs, multiple
     test categories, a foundation plus consumers), implement the
     single most foundational one fully and list the rest as a
     checklist of follow-ups in the PR body — do not attempt all of
     them in one run.
   - **Commit incrementally** after each working slice so partial
     progress is never lost to a timeout.
   - **If the plan declares a dependency** on another issue or PR that
     has not yet merged, do not implement against missing
     infrastructure — open a draft PR noting the blocker and stop.
   - **If you are running low on time**, stop writing new code, open a
     **draft** PR with what is done plus a `## Remaining work`
     checklist, and use `report_incomplete`. A draft PR with partial
     progress is always better than no output.
2. For every production code change, write a corresponding selftest
   under `selftests/` (matching this repo's convention of every fix or
   feature shipping with a test).
3. Run `uv run ruff check src/ selftests/ src/vip_tests/ examples/`
   and fix lint failures.
4. Run `uv run ruff format --check src/ selftests/ src/vip_tests/ examples/`
   and fix format failures.
5. Apply the **same** scope guards as the triage workflow (see
   `issue-triage.md` Step 6). If a guard is tripped, fall through to
   Step 5.

## Step 4 — open implementation PR

Use `create-pull-request`. Title:

```
feat(<scope>): <short description> (closes #<issue-num>)
```

or `fix(<scope>): ...` if the plan describes a bug fix. Validate with
`npx commitlint --extends @commitlint/config-conventional` on the
proposed title before opening.

Branch name: `bot-implement-issue-<num>`.

PR body must include:

- `Closes #<issue-num>`
- "Implements the plan from #<plan-pr-num>"
- A summary of what changed and why
- A `## Demo` section sourced from
  `validation_docs/demo-bot-implement-issue-<num>.md`, generated as:

  ```bash
  uvx showboat init demo.md "Implement: #<num> — <title>"
  uvx showboat exec demo.md bash "uv run pytest selftests/<new-test>.py -v 2>&1 | sed 's/ in [0-9.]*s//'"
  uvx showboat exec demo.md bash "uv run ruff check src/ selftests/"
  just demo-save bot-implement-issue-<num>
  ```

Then update the originating issue (`#<issue-num>`, which you know) so its
labels reflect that implementation has started:

1. Ensure the `implementing` label exists (idempotent):

   ```
   gh label create implementing --color 1D76DB --description "Plan merged; implementation PR in flight" --force
   ```

2. Move the issue from "plan pending" to "implementing" by calling the
   safe-output tools with the issue number as the target (these outputs
   are configured with `target: "*"`, so you must pass
   `issue_number: <issue-num>`):
   - `remove_labels` with `{"labels": ["plan-pending-review"], "issue_number": <issue-num>}`
   - `add_labels` with `{"labels": ["implementing"], "issue_number": <issue-num>}`

3. Add one comment on the issue (`add_comment` with
   `issue_number: <issue-num>`) saying implementation is in progress. Do
   **not** reference the new implementation PR's number — you cannot know
   it while the run is in progress, and you must not invent a placeholder
   such as `#aw_impl<n>`. gh-aw automatically posts a "Related Items" link
   to the new PR on this plan PR, so the cross-link is handled for you;
   describe the work in prose only.

## Step 5 — bail to comment

If the plan is ambiguous, scope-guards trip, or implementation cannot
be completed cleanly, post one comment on the merged plan PR:

```markdown
🤖 I tried to implement this plan automatically but stopped because:

<reason>

A maintainer will need to take it from here.

<!-- vip-triage-bot:v1 status=implementation-blocked plan-pr=<plan-pr-num> -->
```

Do not open a PR in this case.

## Behavior rules

- Operate on the merged plan PR's content only. Do not re-read or
  re-classify the originating issue.
- Never push to `main` directly.
- If `create-pull-request` fails (e.g., branch already exists from a
  previous attempt), append a numeric suffix to the branch name and
  retry once. If still failing, fall through to Step 5.
