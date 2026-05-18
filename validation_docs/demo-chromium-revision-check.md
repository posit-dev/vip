# Fix: chromium_installed must respect Playwright's pinned revision

*2026-05-15T15:50:00Z by Showboat 0.6.1*
<!-- showboat-id: 80bfac09-f421-493d-863d-1838b1de05d6 -->

Before this change, `chromium_installed()` returned True for any `chromium-*` directory under the Playwright cache. When the pinned Playwright version bumped (e.g. from chromium-1208 to chromium-1217), `vip install` saw the old directory and reported "nothing to install" — even though Playwright itself would fail at launch with a 'please run playwright install' message.

The fix reads the current build revision from `playwright/driver/package/browsers.json` and checks for that specific `chromium-<revision>` directory. If Playwright isn't importable or the file is missing, we fall back to the old loose check so a broken Playwright install doesn't block `vip install` from running.

## Repro: stale cache hides the missing build

The current playwright pin is 1.59.0, which expects `chromium-1217`. We point the cache at a fresh tmpdir, drop in a stale `chromium-1208` directory, and confirm `vip install --dry-run` now correctly plans to install chromium instead of saying 'nothing to install'.

```bash
set -eu
DEMO_CACHE="/tmp/vip-demo-stale-cache"
rm -rf "$DEMO_CACHE"
mkdir -p "$DEMO_CACHE/chromium-1208"
PLAYWRIGHT_BROWSERS_PATH="$DEMO_CACHE" uv run vip install --dry-run
rm -rf "$DEMO_CACHE"
```

```output
vip install plan (macos ):
  playwright: install chromium into /tmp/vip-demo-stale-cache
```

## Repro: a matching cache is still recognized

Now the same tmpdir but with the *current* expected revision (`chromium-1217`) pre-populated. `vip install` correctly says there's nothing to do.

```bash
set -eu
DEMO_CACHE="/tmp/vip-demo-current-cache"
rm -rf "$DEMO_CACHE"
mkdir -p "$DEMO_CACHE/chromium-1217"
PLAYWRIGHT_BROWSERS_PATH="$DEMO_CACHE" uv run vip install --dry-run
rm -rf "$DEMO_CACHE"
```

```output
vip install: nothing to install.
```

## Fallback: no Playwright available

If `expected_chromium_revision()` cannot determine the pinned revision (e.g. broken Playwright install), `chromium_installed()` falls back to the old behavior of accepting any `chromium-*` directory so users aren't blocked from running `vip install` while debugging.

```bash
uv run python -c "
from pathlib import Path
import tempfile
from vip.install import playwright as pw

with tempfile.TemporaryDirectory() as d:
    cache = Path(d)
    (cache / \"chromium-1208\").mkdir()
    # Explicit revision=None and monkey-patched lookup returning None
    pw.expected_chromium_revision = lambda: None
    print(\"fallback accepts any chromium-* dir:\", pw.chromium_installed(cache))
"
```

```output
fallback accepts any chromium-* dir: True
```

## Tests

New test cases in `selftests/install/test_playwright.py` cover:
- the bug repro (stale revision in cache, current revision missing → False)
- positive case with explicit revision
- default revision lookup via `expected_chromium_revision()`
- fallback when the revision cannot be determined
- the live read of `browsers.json` from the installed playwright package

Run the full selftest suite and strip the elapsed-time suffix so re-runs verify cleanly:

```bash
uv run pytest selftests/install/test_playwright.py -q 2>&1 | tail -1 | sed 's/ in [0-9.]*s//'
```

```output
16 passed
```

```bash
uv run ruff check src/ selftests/ examples/ docker/ 2>&1
uv run ruff format --check src/ selftests/ examples/ docker/ 2>&1
```

```output
All checks passed!
128 files already formatted
```
