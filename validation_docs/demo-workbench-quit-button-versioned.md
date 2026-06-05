# fix(workbench): match versioned Quit button across releases

*2026-06-05T16:35:04Z by Showboat 0.6.1*
<!-- showboat-id: 68831fb4-85b8-4a1c-882a-c635c1a4a823 -->

The IDE-launch smoke tests against the latest Workbench (2026.05.0) failed at the Quit-session cleanup step. Workbench now renders the homepage Quit button as "Quit (N)" (N = selected sessions) instead of plain "Quit".

The prior fix used a CSS text-matches regex selector: button:text-matches('^Quit( \(\d+\))?$'). That silently matched ZERO "Quit (1)" buttons, because Playwright's selector parser consumes one level of backslash escaping inside the quoted argument, mangling the regex (\( -> (, \d -> d) into ^Quit( (d+))?$ -- which only matches a bare "Quit".

Fix: drop the regex and use a comma-separated selector that mirrors the existing cross-version session_row_status pattern. It matches the old exact "Quit" AND any new "Quit (N)", while the has-text 'Quit (' clause excludes the separate "Quit All" button.

```bash
grep -n 'QUIT_BUTTON =' src/vip_tests/workbench/pages/homepage.py
```

```output
96:    QUIT_BUTTON = "button:text-is('Quit'), button:has-text('Quit (')"
```

```bash
cat > /tmp/vip_quit_check.py <<"PY"
import sys
sys.path.insert(0, "src")
from vip_tests.workbench.pages.homepage import Homepage
from playwright.sync_api import sync_playwright

SEL = Homepage.QUIT_BUTTON
cases = [
    ("old WB: Quit + Quit All", "<button>Quit</button><button>Quit All</button>", "Quit"),
    ("new WB: Quit (1) + Quit All", "<button>Quit (1)</button><button>Quit All</button>", "Quit (1)"),
    ("new WB: Quit (3) selected", "<button>Quit (3)</button><button>Quit All</button>", "Quit (3)"),
]
with sync_playwright() as p:
    b = p.chromium.launch()
    for name, html, expect in cases:
        pg = b.new_page()
        pg.set_content("<html><body>" + html + "</body></html>")
        loc = pg.locator(SEL)
        texts = [loc.nth(i).inner_text() for i in range(loc.count())]
        verdict = "PASS" if texts == [expect] else "FAIL"
        print(verdict + " | " + name + " -> matched " + repr(texts))
        pg.close()
    b.close()
PY
uv run python /tmp/vip_quit_check.py 2>&1 | grep -vE "WARNING|cachecontrol"
```

```output
PASS | old WB: Quit + Quit All -> matched ['Quit']
PASS | new WB: Quit (1) + Quit All -> matched ['Quit (1)']
PASS | new WB: Quit (3) selected -> matched ['Quit (3)']
```

Root cause, demonstrated: the previous regex selector matched ZERO "Quit (1)" buttons (it only matched a bare "Quit"), confirming the backslash-escaping bug.

```bash
cat > /tmp/vip_quit_before.py <<"PY"
from playwright.sync_api import sync_playwright

OLD = "button:text-matches(" + chr(39) + "^Quit( \\(\\d+\\))?$" + chr(39) + ")"
NEW = "button:text-is(" + chr(39) + "Quit" + chr(39) + "), button:has-text(" + chr(39) + "Quit (" + chr(39) + ")"
html = "<html><body><button>Quit (1)</button><button>Quit All</button></body></html>"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.set_content(html)
    for label, sel in [("OLD regex selector", OLD), ("NEW comma selector", NEW)]:
        loc = pg.locator(sel)
        texts = [loc.nth(i).inner_text() for i in range(loc.count())]
        print(label + ": matched " + repr(texts))
    b.close()
PY
uv run python /tmp/vip_quit_before.py 2>&1 | grep -vE "WARNING|cachecontrol"
```

```output
OLD regex selector: matched []
NEW comma selector: matched ['Quit (1)']
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1 && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -1
```

```output
All checks passed!
139 files already formatted
```
