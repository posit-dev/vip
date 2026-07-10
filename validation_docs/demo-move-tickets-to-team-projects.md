# Feature: route team-labeled issues to product boards

*2026-07-02T00:31:14Z by Showboat 0.6.1*
<!-- showboat-id: 5dfa34c6-75ad-451f-bbb6-b6e52b8de5b7 -->

Issue #413: route team-labeled issues onto product team project boards. Adds .github/workflows/add-to-team-project.yml — when a 'team: connect', 'team: workbench', or 'team: package manager' label is applied to an issue, the issue is added to that product team's org-level GitHub project board via a cross-org GitHub App token. Ported from rstudio/helm's issues.yml, dropping the chronicle and launcher teams. Also creates the three team labels the workflow keys off of.

```bash
cat .github/workflows/add-to-team-project.yml
```

```output
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
        if: steps.project-url.outputs.PROJECT != 'none'
        uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1  # v3.2.0
        with:
          client-id: ${{ secrets.POSIT_PLATFORM_CLIENT_ID }}
          private-key: ${{ secrets.POSIT_PLATFORM_PEM }}
          owner: ${{ steps.project-url.outputs.ORG }}
          permission-organization-projects: write

      - name: Add issue to project
        id: add-to-project
        if: steps.project-url.outputs.PROJECT != 'none'
        uses: actions/add-to-project@5afcf98fcd03f1c2f92c3c83f58ae24323cc57fd  # v2.0.0
        with:
          project-url: ${{ steps.project-url.outputs.PROJECT }}
          github-token: ${{ steps.generate-token.outputs.token }}
          labeled: ${{ github.event.label.name }}
```

```bash
uv run python -c "import yaml; d=yaml.safe_load(open('.github/workflows/add-to-team-project.yml')); print('valid YAML; trigger =', d[True]['issues']['types'], '; permissions =', d['permissions'])"
```

```output
valid YAML; trigger = ['labeled'] ; permissions = {}
```

```bash
gh label list --repo posit-dev/vip --search team --json name,color --jq '.[] | select(.name|startswith("team")) | .name + "  #" + .color' | sort
```

```output
team: connect  #BF4EEC
team: package manager  #BF4EEC
team: workbench  #BF4EEC
```
