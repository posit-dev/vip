---
on:
  workflow_run:
    workflows: ["Website Preview"]
    types: [completed]
    branches: ["**"]
permissions: read-all
tools:
  github:
    toolsets: [default]
    github-app:
      client-id: ${{ secrets.POSIT_VIP_TRIAGE_CLIENT_ID }}
      private-key: ${{ secrets.POSIT_VIP_TRIAGE_PEM }}
  playwright:
    mode: cli
    version: "0.1.13"
safe-outputs:
  github-app:
    client-id: ${{ secrets.POSIT_VIP_TRIAGE_CLIENT_ID }}
    private-key: ${{ secrets.POSIT_VIP_TRIAGE_PEM }}
  upload-asset:
    branch: assets/preview-screenshot-gallery
    max: 100
  add-comment:
    max: 1
network:
  allowed:
    - defaults
    - playwright
    - posit-dev.github.io
---

# Capture preview screenshots for PRs

When this workflow runs:

1. Confirm the triggering workflow run succeeded (`conclusion == success`). If it did not, stop.
2. Read `github.event.workflow_run.pull_requests` and find the first PR number. If no PR is attached, stop.
3. Compute preview URLs for that PR number:
   - Website: `https://posit-dev.github.io/vip/pr-preview-site/pr-<PR_NUMBER>/`
   - Report: `https://posit-dev.github.io/vip/pr-preview/pr-<PR_NUMBER>/`

Take screenshots with Playwright (CLI mode) and attach them to the PR. Use `playwright-cli` bash commands directly — not MCP browser tools. The relevant commands are:

- `playwright-cli browser_navigate --url <URL>` — load a page
- `playwright-cli browser_take_screenshot --filename <PATH> --full-page true` — capture a full-page screenshot
- `playwright-cli browser_snapshot` — dump the current DOM (use this when you need page contents to extract links)
- `playwright-cli browser_evaluate --expression "<JS>"` — run JavaScript in the page (e.g., to extract all `<a href>` values)

Workflow body:

1. Create a temporary output folder under `/tmp` (e.g., `mkdir -p /tmp/preview-screenshots`).
2. Visit the website preview URL with `playwright-cli browser_navigate` and take a full-page screenshot of the landing page.
3. Crawl all same-origin links reachable from the website preview base path (`/vip/pr-preview-site/pr-<PR_NUMBER>/`):
   - Use `playwright-cli browser_evaluate` with an expression like `Array.from(document.querySelectorAll('a[href]')).map(a => a.href)` to extract links.
   - Filter to same-origin URLs under the preview base path. Deduplicate. Skip anchors (`#fragment`) and external links.
   - For each unique URL, `browser_navigate` then `browser_take_screenshot`.
4. Visit the report preview URL and take a full-page screenshot of the landing page.
5. Crawl all same-origin links reachable from the report preview base path (`/vip/pr-preview/pr-<PR_NUMBER>/`) using the same approach as step 3.
6. Name files clearly so reviewers can identify each source page (for example, prefix with `website-` or `report-`).
7. Upload every screenshot using `upload-asset`.
8. Add one PR comment summarizing:
   - total screenshots uploaded,
   - which URLs were captured,
   - any pages that failed to render/screenshot.
9. In that PR comment, render screenshots inline using Markdown image syntax (for example, `![website home](<asset-url>)`) so images are directly visible in the comment body, not just linked.

Quality checks:
- Use full-page screenshots (`--full-page true`).
- Wait for the page to be stable before capturing — if a page is JS-heavy, give it a moment after `browser_navigate` (a brief `sleep` or a re-check via `browser_snapshot` for content readiness).
- Continue even if a subset of pages fail; report failures in the final PR comment.
