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
  playwright:
safe-outputs:
  upload-asset:
    branch: assets/preview-screenshot-gallery
    max: 100
  add-comment:
    max: 1
network:
  allowed:
    - defaults
    - posit-dev.github.io
---

# Capture preview screenshots for PRs

When this workflow runs:

1. Confirm the triggering workflow run succeeded (`conclusion == success`). If it did not, stop.
2. Read `github.event.workflow_run.pull_requests` and find the first PR number. If no PR is attached, stop.
3. Compute preview URLs for that PR number:
   - Website: `https://posit-dev.github.io/vip/pr-preview-site/pr-<PR_NUMBER>/`
   - Report: `https://posit-dev.github.io/vip/pr-preview/pr-<PR_NUMBER>/`

Take screenshots with Playwright and attach them to the PR:

1. Create a temporary output folder under `/tmp`.
2. Visit the website preview URL and take a full-page screenshot of the landing page.
3. Crawl all same-origin links reachable from the website preview base path (`/vip/pr-preview-site/pr-<PR_NUMBER>/`), deduplicate URLs, skip anchors and external links, and take one full-page screenshot per page.
4. Visit the report preview URL and take a full-page screenshot of the landing page.
5. Crawl all same-origin links reachable from the report preview base path (`/vip/pr-preview/pr-<PR_NUMBER>/`), deduplicate URLs, skip anchors and external links, and take one full-page screenshot per page.
6. Name files clearly so reviewers can identify each source page (for example, prefix with `website-` or `report-`).
7. Upload every screenshot using `upload-asset`.
8. Add one PR comment summarizing:
   - total screenshots uploaded,
   - which URLs were captured,
   - any pages that failed to render/screenshot.

Quality checks:
- Use full-page screenshots.
- Wait for the page to be stable before capturing.
- Continue even if a subset of pages fail; report failures in the final PR comment.
