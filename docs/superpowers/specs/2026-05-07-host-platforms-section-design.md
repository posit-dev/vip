# Host platforms section on the feature matrix page

## Background

`website/src/pages/feature-matrix.astro` shows a test-coverage matrix
(test areas × Connect/Workbench/Package Manager) but says nothing about
*where you can run VIP itself*. Since 0.29.0 (PR #241) `vip install` and
`vip uninstall` officially support several host platforms, and CI now
exercises all of them on every change:

| Platform          | Where exercised                                        |
| ----------------- | ------------------------------------------------------ |
| Ubuntu            | `ci.yml` (selftests on `ubuntu-latest`)                |
| RHEL 9            | `linux-smoke.yml` (`redhat/ubi9` container)            |
| RHEL 10           | `linux-smoke.yml` (`redhat/ubi10` container)           |
| openSUSE Leap 15  | `linux-smoke.yml` (`opensuse/leap:15` container)       |
| macOS             | `mac-smoke.yml` + selftests on `macos-latest`          |

The feature-matrix page is the natural home for this — readers go there
to understand what VIP covers, and host support is part of that picture.

## Scope

Add a new **Host platforms** section to `feature-matrix.astro`,
positioned between the existing test-coverage matrix and the
**Not Yet Covered** section.

Out of scope:
- Editing `feature-matrix.json` or any data layer (the platform list
  rarely changes, lives well as static markup).
- Per-OS install instructions (those belong on `getting-started.astro`).
- Documenting family-supported but untested distros (Fedora, Rocky,
  AlmaLinux, CentOS, OL, Debian, SLES, openSUSE Tumbleweed). The page
  reflects what CI actually exercises.

## Design

### Layout

A heading + short description + grid of cards, sized using the same
auto-fill grid pattern as the existing `not-covered-grid`
(`repeat(auto-fill, minmax(280px, 1fr))`). On a typical desktop width
this lays out as 3 cards on the first row and 2 on the second; on
narrow screens it collapses to a single column.

```
Host platforms
Platforms where `vip install` is supported and verified on every change.

[ ✓ Ubuntu ]   [ ✓ RHEL 9 ]   [ ✓ RHEL 10 ]
[ ✓ openSUSE Leap 15 ]   [ ✓ macOS ]
```

### Content

- **Heading:** `Host platforms`
- **Description:** *Platforms where `vip install` is supported and
  verified on every change.*
- **Five cards**, each containing only a green checkmark icon and the
  platform name. No subtitle, no architecture note, no "CI tested"
  wording on the card itself.

### Card order

Linux distros first, grouped by family, with macOS last:

1. Ubuntu
2. RHEL 9
3. RHEL 10
4. openSUSE Leap 15
5. macOS

### Markup

A new pair of CSS classes that mirror the existing
`not-covered-grid` / `not-covered-card` structure but use the page's
existing "covered" green (`#22c55e`, the same color as `.dot-covered`)
for the icon. The icon is a checkmark glyph (`&#10003;`) rather than
the empty-state circle (`&#9711;`) used by `not-covered-card`.

Sketch (final markup applied during implementation, not in this spec):

```astro
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
    <!-- RHEL 9, RHEL 10, openSUSE Leap 15, macOS -->
  </div>
</div>
```

CSS reuses spacing and border treatments from `not-covered-card`. The
icon color is `#22c55e` instead of `var(--posit-text-muted)`. No new
top-level layout primitives.

### Cross-links

None. The page header already provides navigation; no per-section link
to `getting-started`.

### Source of truth

The list lives as static markup in `feature-matrix.astro`. It does not
read from `feature-matrix.json`. Rationale:

- The list changes only when CI gains or drops a platform — roughly
  once per release at most.
- `feature-matrix.json` is shaped around test-coverage data
  (areas × products × scenario counts) and has no natural slot for a
  host-platform list.
- A static block keeps the change localized and easy to review.

When a new platform is added (or removed) from CI, the update is a
one-line edit in this file.

## Acceptance criteria

- A "Host platforms" section appears between the test-coverage matrix
  and the "Not Yet Covered" section on `/feature-matrix/`.
- Five cards render in the order: Ubuntu, RHEL 9, RHEL 10, openSUSE
  Leap 15, macOS.
- Each card shows a green checkmark and the platform name only.
- The grid collapses to one column under the existing 768px mobile
  breakpoint.
- No changes to `feature-matrix.json`, the test matrix table, or the
  "Not Yet Covered" cards.
- No "CI smoke" / "CI tested" wording appears on the cards.

## Risks and follow-ups

- **Drift**: when CI gains or drops a platform, this section must be
  updated by hand. A short comment in the markup pointing at
  `.github/workflows/linux-smoke.yml` and `mac-smoke.yml` mitigates
  this. (Implementation detail, not part of the design contract.)
- **Family coverage messaging**: the page intentionally lists only
  CI-exercised platforms. If users start asking why Debian/Fedora/SLES
  aren't listed despite working in practice, a future revision could
  add a small note ("RHEL family, Debian family, SUSE family also
  supported"). Out of scope for this change.
