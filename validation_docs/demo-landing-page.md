# Feature: Astro Landing Page for VIP

*2026-03-10T04:17:26Z by Showboat 0.6.1*
<!-- showboat-id: cc50e5a5-95eb-4901-8ad9-cea00ba7e3b3 -->

Created an AstroJS website for the VIP project with a landing page and getting started page, styled with the Posit design system (colors, typography, and layout patterns from docs.posit.co and posit.co). The site is configured for GitHub Pages deployment via a dedicated workflow.

```bash
find website/src -name '*.astro' -o -name '*.css' | sort
```

```output
website/src/components/Footer.astro
website/src/components/Header.astro
website/src/layouts/Layout.astro
website/src/pages/getting-started.astro
website/src/pages/index.astro
website/src/styles/global.css
```

```bash
cat website/astro.config.mjs
```

```output
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://posit-dev.github.io",
  base: "/vip/",
});
```

```bash
head -6 website/package.json
```

```output
{
  "name": "vip-website",
  "type": "module",
  "private": true,
  "scripts": {
    "dev": "astro dev",
```

```bash
cat .github/workflows/website.yml
```

```output
name: Deploy Website to GitHub Pages

on:
  push:
    branches: [main]
    paths:
      - "website/**"
      - ".github/workflows/website.yml"
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
        with:
          persist-credentials: false

      - uses: withastro/action@15aa0a5a1e067940253e3b259413ab2ae882a740 # v5.2.0
        with:
          path: ./website

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e # v4.0.5
```

All actions are SHA-pinned. Workflow deploys on pushes to main that change website/** files. The withastro/action handles npm install, build, and upload-pages-artifact automatically.
