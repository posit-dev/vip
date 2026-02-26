# Plan: Showboat demos for agent-authored PRs

_Related issue: Require Claude Code and Copilot PRs to include demos._

## Goal

Make Showboat demos a standard requirement for PRs opened by coding
agents, and make those demos visible directly in each PR.

## Repository policy

1. Agent-authored PRs must include a Showboat demo.
2. The PR description must include a **Showboat demo** section.
3. The section must contain:
   - an embedded attachment or published Showboat URL, and
   - the command(s) used to produce the demo.

## Session workflow for agents

1. Implement the change.
2. Record a short Showboat demo that proves the change works.
3. Update the PR description with:
   - demo media/link,
   - replay commands,
   - a one-line statement of what the demo shows.

## Enforcement in this repo

- `AGENTS.md` documents the Showboat requirement for coding agents.
- `.github/pull_request_template.md` adds a required Showboat section and
  checklist item so PRs consistently include demos.
