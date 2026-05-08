# Host platforms section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Host platforms" section to the feature matrix page listing the five CI-exercised platforms (Ubuntu, RHEL 9, RHEL 10, openSUSE Leap 15, macOS) as cards.

**Architecture:** Single-file change to `website/src/pages/feature-matrix.astro`. The new section is placed between the existing test matrix and the "Not Yet Covered" section. Markup and CSS mirror the existing `not-covered-grid` / `not-covered-card` pattern with a green checkmark glyph instead of the muted empty-state circle. Card list is static markup; no JSON wiring.

**Tech Stack:** Astro 5.x (static site), plain HTML/CSS, no JS. Build with `npm run build` from `website/`.

**Spec:** `docs/superpowers/specs/2026-05-07-host-platforms-section-design.md`

---

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `website/src/pages/feature-matrix.astro` | Modify | Add the new `host-platforms-section` block (markup + scoped CSS) |

No new files. No JSON or data layer changes. No CSS variable additions — reuse `--posit-border`, `--posit-gray-900`, `--posit-text-muted`, `--posit-navy`, `--radius`, and the literal `#22c55e` already used on the page.

---

### Task 1: Add the Host platforms section to feature-matrix.astro

**Files:**
- Modify: `website/src/pages/feature-matrix.astro` (insert markup before line 131, append CSS after line 433)

- [ ] **Step 1: Insert the section markup before the existing "Not Yet Covered" section**

The existing block starting at line 130 looks like:

```astro
      {/* Not yet covered section */}
      <div class="not-covered-section">
        <h2>Not Yet Covered</h2>
```

Insert this block immediately before that `{/* Not yet covered section */}` comment (so the new section appears between the matrix and "Not Yet Covered"):

```astro
      {/* Host platforms section */}
      <div class="host-platforms-section">
        <h2>Host platforms</h2>
        <p class="host-platforms-desc">
          Platforms where <code>vip install</code> is supported and verified
          on every change.
        </p>
        <div class="host-platforms-grid">
          <div class="host-platform-card">
            <span class="host-platform-icon">&#10003;</span>
            <strong>Ubuntu</strong>
          </div>
          <div class="host-platform-card">
            <span class="host-platform-icon">&#10003;</span>
            <strong>RHEL 9</strong>
          </div>
          <div class="host-platform-card">
            <span class="host-platform-icon">&#10003;</span>
            <strong>RHEL 10</strong>
          </div>
          <div class="host-platform-card">
            <span class="host-platform-icon">&#10003;</span>
            <strong>openSUSE Leap 15</strong>
          </div>
          <div class="host-platform-card">
            <span class="host-platform-icon">&#10003;</span>
            <strong>macOS</strong>
          </div>
        </div>
      </div>

```

Card order is locked by the spec: Ubuntu, RHEL 9, RHEL 10, openSUSE Leap 15, macOS.

- [ ] **Step 2: Add the CSS for the new section to the existing `<style>` block**

The existing `<style>` block ends with the mobile media query at lines 435-447. Append the new rules immediately *before* the existing `@media (max-width: 768px)` block, then add a `host-platforms-grid` rule *inside* that media query so the grid collapses on mobile.

First, insert this CSS block right before `@media (max-width: 768px) {` (i.e. after the existing `.not-covered-reason { ... }` rule):

```css
  /* Host platforms */
  .host-platforms-section {
    margin-top: 2.5rem;
    margin-bottom: 2.5rem;
  }

  .host-platforms-section h2 {
    font-size: 1.25rem;
    font-weight: 700;
    color: var(--posit-navy);
    margin-bottom: 0.5rem;
  }

  .host-platforms-desc {
    color: var(--posit-text-muted);
    font-size: 0.9375rem;
    margin-bottom: 1.25rem;
  }

  .host-platforms-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 0.75rem;
  }

  .host-platform-card {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    background: white;
    border: 1px solid var(--posit-border);
    border-radius: var(--radius);
    padding: 1rem 1.25rem;
    border-left: 3px solid #22c55e;
  }

  .host-platform-icon {
    color: #22c55e;
    font-size: 1rem;
    font-weight: 700;
    flex-shrink: 0;
  }

  .host-platform-card strong {
    font-size: 0.9375rem;
    color: var(--posit-gray-900);
  }

```

Then, inside the existing `@media (max-width: 768px) { ... }` block (which currently contains `.legend`, `.area-cell`, and `.not-covered-grid` rules), add this rule alongside the others:

```css
    .host-platforms-grid {
      grid-template-columns: 1fr;
    }
```

- [ ] **Step 3: Build the site to confirm Astro accepts the changes**

Run from the `website/` directory:

```bash
cd website
npm run build
```

Expected: build completes with no errors. The `dist/feature-matrix/index.html` file is regenerated. If the build fails, the most likely cause is a stray bracket or unclosed tag from Step 1 — re-read the inserted block and check the surrounding `</main>` / `</Layout>` closing tags are still in place.

- [ ] **Step 4: Visually verify in the dev server**

Start the dev server:

```bash
npm run dev
```

Open the printed URL (usually `http://localhost:4321/vip/feature-matrix/`) and confirm:

1. A new "Host platforms" heading appears between the test matrix table and the "Not Yet Covered" cards.
2. Five cards render in this exact left-to-right / top-to-bottom order: Ubuntu, RHEL 9, RHEL 10, openSUSE Leap 15, macOS.
3. Each card shows a green checkmark followed by the platform name only. No "CI", "tested", or "smoke" wording on the cards.
4. The cards have a green left border (matching the checkmark color) and otherwise look like the "Not Yet Covered" cards.
5. Resize the browser narrow (<768px). The grid collapses to a single column.

Stop the dev server (Ctrl+C) once verified.

- [ ] **Step 5: Commit**

From the repo root:

```bash
git add website/src/pages/feature-matrix.astro
git commit -m "feat(website): add host platforms section to feature matrix"
```

---

## Self-review checklist

After implementation, before declaring done:

- [ ] Section appears between the matrix and "Not Yet Covered" — not above the matrix, not below "Not Yet Covered".
- [ ] Card order is exactly Ubuntu → RHEL 9 → RHEL 10 → openSUSE Leap 15 → macOS.
- [ ] Cards contain only the checkmark and platform name. No subtitle, no architecture note, no CI wording.
- [ ] `npm run build` succeeds.
- [ ] Mobile breakpoint collapses the grid to one column.
- [ ] No changes outside `website/src/pages/feature-matrix.astro`.
- [ ] No edits to `feature-matrix.json`.
