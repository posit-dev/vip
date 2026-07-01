# Move Tickets to Team Projects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a `team: <product>` label is added to a vip issue, automatically add that issue to the matching product team's org-level GitHub project board.

**Architecture:** A single GitHub Actions workflow triggered on `issues: labeled`. Step 1 maps the label to a project URL + org (or `none`). If a team label matched, step 2 mints a cross-org GitHub App token and step 3 adds the issue to that org's project board. Ported from `rstudio/helm`'s `issues.yml`, dropping chronicle/launcher. Plus three new repo labels the workflow keys off of.

**Tech Stack:** GitHub Actions YAML; `actions/create-github-app-token` v3.2.0; `actions/add-to-project` v2.0.0; `gh` CLI for label creation.

## Global Constraints

- Action pins must use full commit SHA + `# vX.Y.Z` comment (repo convention).
  - `actions/create-github-app-token` → `bcd2ba49218906704ab6c1aa796996da409d3eb1` (v3.2.0)
  - `actions/add-to-project` → `5afcf98fcd03f1c2f92c3c83f58ae24323cc57fd` (v2.0.0)
- Project boards / orgs (carried over from helm, unchanged):
  - `team: connect` → `https://github.com/orgs/posit-dev/projects/23`, org `posit-dev`
  - `team: workbench` → `https://github.com/orgs/rstudio/projects/92`, org `rstudio`
  - `team: package manager` → `https://github.com/orgs/rstudio/projects/48`, org `rstudio`
- Auth secrets: `POSIT_PLATFORM_APP_ID`, `POSIT_PLATFORM_PEM` (cross-org app, same as helm).
- Labels: color `BF4EEC`; descriptions `Posit <Product> related issue`.
- PR title must be conventional commit format (CI-enforced). Suggested: `feat: add workflow to route team-labeled issues to product boards`.

---

### Task 1: Add the team-project routing workflow + docs

**Files:**
- Create: `.github/workflows/add-to-team-project.yml`
- Modify: `CLAUDE.md` (the "CI workflows" bullet list, around line 231)

**Interfaces:**
- Consumes: repo secrets `POSIT_PLATFORM_APP_ID`, `POSIT_PLATFORM_PEM` (runtime only; not needed to author/verify the file).
- Produces: workflow file `add-to-team-project.yml` — the deliverable Task 3 demos.

> **Note on TDD:** This task's deliverable is declarative CI config, not code with a
> unit-test harness. The "test" is YAML validity + structural assertions on the file
> contents (trigger, all three label→project mappings, pinned action SHAs). Write those
> assertions as a shell check and run them; that is the test cycle for this task.

- [ ] **Step 1: Write the workflow file**

Create `.github/workflows/add-to-team-project.yml` with exactly this content. Note the label name is read via an `env:` var (`LABEL_NAME`) rather than interpolated directly into the shell — this avoids script injection and is the only deliberate deviation from helm.

```yaml
# When an issue is labeled with a team label, add it to that product team's
# org-level GitHub project board.
# Ported from rstudio/helm .github/workflows/issues.yml (chronicle/launcher dropped).
name: Add to team project

on:
  issues:
    types:
      - labeled

permissions: {}

jobs:
  add-to-team-project:
    runs-on: ubuntu-latest
    steps:
      - name: Map label to project URL
        id: project-url
        env:
          LABEL_NAME: ${{ github.event.label.name }}
        run: |
          if [ "$LABEL_NAME" = "team: connect" ]; then
            echo "PROJECT=https://github.com/orgs/posit-dev/projects/23" >> "$GITHUB_OUTPUT"
            echo "ORG=posit-dev" >> "$GITHUB_OUTPUT"
          elif [ "$LABEL_NAME" = "team: workbench" ]; then
            echo "PROJECT=https://github.com/orgs/rstudio/projects/92" >> "$GITHUB_OUTPUT"
            echo "ORG=rstudio" >> "$GITHUB_OUTPUT"
          elif [ "$LABEL_NAME" = "team: package manager" ]; then
            echo "PROJECT=https://github.com/orgs/rstudio/projects/48" >> "$GITHUB_OUTPUT"
            echo "ORG=rstudio" >> "$GITHUB_OUTPUT"
          else
            echo "PROJECT=none" >> "$GITHUB_OUTPUT"
          fi

      - name: Generate token for GitHub App
        id: generate-token
        if: steps.project-url.outputs.project != 'none'
        uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1  # v3.2.0
        with:
          app-id: ${{ secrets.POSIT_PLATFORM_APP_ID }}
          private-key: ${{ secrets.POSIT_PLATFORM_PEM }}
          owner: ${{ steps.project-url.outputs.ORG }}
          permission-organization-projects: write

      - name: Add issue to project
        id: add-to-project
        if: steps.project-url.outputs.project != 'none'
        uses: actions/add-to-project@5afcf98fcd03f1c2f92c3c83f58ae24323cc57fd  # v2.0.0
        with:
          project-url: ${{ steps.project-url.outputs.PROJECT }}
          github-token: ${{ steps.generate-token.outputs.token }}
          labeled: ${{ github.event.label.name }}
```

- [ ] **Step 2: Verify the workflow is valid YAML and structurally correct**

Run:

```bash
uv run python -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/add-to-team-project.yml')); assert d[True]['issues']['types']==['labeled'], 'trigger'; assert d['permissions']=={}, 'permissions'; print('yaml OK')"
grep -q 'orgs/posit-dev/projects/23' .github/workflows/add-to-team-project.yml && \
grep -q 'orgs/rstudio/projects/92' .github/workflows/add-to-team-project.yml && \
grep -q 'orgs/rstudio/projects/48' .github/workflows/add-to-team-project.yml && \
grep -q 'create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1' .github/workflows/add-to-team-project.yml && \
grep -q 'add-to-project@5afcf98fcd03f1c2f92c3c83f58ae24323cc57fd' .github/workflows/add-to-team-project.yml && \
echo "structure OK"
```

Expected: prints `yaml OK` then `structure OK`. (`d[True]` is correct — PyYAML parses the bare `on:` key as boolean `True`.)

- [ ] **Step 3: Add the CLAUDE.md docs row**

In `CLAUDE.md`, under `## CI workflows`, insert a new bullet immediately after the `implement-plan.md` bullet (currently the last in the list, ~line 231):

```markdown
-   **`add-to-team-project.yml`** -- when a `team: connect`, `team: workbench`, or `team: package manager` label is added to an issue, adds it to that product team's org-level GitHub project board. Ported from rstudio/helm. Requires the cross-org `POSIT_PLATFORM_APP_ID`/`POSIT_PLATFORM_PEM` app secrets.
```

- [ ] **Step 4: Re-run the structural check to confirm nothing broke**

Run: `uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/add-to-team-project.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/add-to-team-project.yml CLAUDE.md
git commit -m "feat: add workflow to route team-labeled issues to product boards"
```

---

### Task 2: Create the three team labels in the repo

**Files:** none (operates on the live `posit-dev/vip` repo via `gh`).

**Interfaces:**
- Produces: repo labels `team: connect`, `team: workbench`, `team: package manager` — the workflow from Task 1 is a no-op until these exist and are applied.

- [ ] **Step 1: Create the labels**

Run each as a separate command (idempotent via `--force`):

```bash
gh label create "team: connect" --repo posit-dev/vip --color BF4EEC --description "Posit Connect related issue" --force
gh label create "team: workbench" --repo posit-dev/vip --color BF4EEC --description "Posit Workbench related issue" --force
gh label create "team: package manager" --repo posit-dev/vip --color BF4EEC --description "Posit Package Manager related issue" --force
```

- [ ] **Step 2: Verify the labels exist**

Run: `gh label list --repo posit-dev/vip --search "team" --json name --jq '.[].name'`
Expected: lists `team: connect`, `team: workbench`, `team: package manager`.

*(No commit — labels are repo state, not files.)*

---

### Task 3: Showboat demo + PR

**Files:**
- Create: `validation_docs/demo-move-tickets-to-team-projects.md` (via `just demo-save`)

**Interfaces:**
- Consumes: the workflow file (Task 1) and labels (Task 2).

- [ ] **Step 1: Build the demo**

```bash
uvx showboat init demo.md "Feature: route team-labeled issues to product boards"
uvx showboat note demo.md "Adds .github/workflows/add-to-team-project.yml. When a team label is applied to an issue, the issue is added to that product team's org project board. Ported from rstudio/helm, dropping chronicle/launcher."
uvx showboat exec demo.md bash "cat .github/workflows/add-to-team-project.yml"
uvx showboat exec demo.md bash "uv run python -c \"import yaml; d=yaml.safe_load(open('.github/workflows/add-to-team-project.yml')); print('valid YAML; trigger =', d[True]['issues']['types'])\""
uvx showboat exec demo.md bash "gh label list --repo posit-dev/vip --search team --json name,color --jq '.[] | select(.name|startswith(\"team\")) | .name + \"  #\" + .color'"
```

- [ ] **Step 2: Verify and archive the demo**

Run: `just demo-save move-tickets-to-team-projects`
Expected: `showboat verify` passes; file moves to `validation_docs/demo-move-tickets-to-team-projects.md`.

> If `showboat verify` fails on the `gh label list` block due to output ordering, replace that block's expected output or sort the jq output (`| sort`) so it is deterministic.

- [ ] **Step 3: Commit**

```bash
git add validation_docs/demo-move-tickets-to-team-projects.md
git commit -m "test: add showboat demo for team-project routing workflow"
```

- [ ] **Step 4: Open the PR**

Push the branch and open a PR whose body includes a `## Demo` section (paste the demo contents) and a **Prerequisites** note:

> **Requires org-admin setup before this works at runtime:** `POSIT_PLATFORM_APP_ID` and `POSIT_PLATFORM_PEM` must be available to `posit-dev/vip`, and the GitHub App must be installed on both `posit-dev` and `rstudio` with `organization-projects: write`. End-to-end check (apply `team: connect` to a test issue → it appears on the Connect board) is a manual post-merge step.

Reference `Closes #413` in the PR body.

---

## Cleanup (after implementation completes)

Per user convention: remove this plan (`docs/superpowers/plans/2026-07-01-move-tickets-to-team-projects.md`) and the spec (`docs/superpowers/specs/2026-07-01-move-tickets-to-team-projects-design.md`) once implementation is done, committing the removal.
