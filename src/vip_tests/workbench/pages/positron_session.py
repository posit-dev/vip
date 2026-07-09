"""Positron session selectors.

Mirrors: rstudio-pro/e2e/pages/positron_session.page.ts
"""

from vip_tests.workbench.pages._extensions import EXTENSION_ID_RE


class PositronSession:
    """Selectors for the Positron IDE.

    Positron is based on VS Code, so many selectors are similar.
    """

    # Core UI elements (VS Code based)
    WORKBENCH = ".monaco-workbench"
    STATUS_BAR = ".statusbar"
    ACTIVITY_BAR = ".activitybar"
    SIDEBAR = ".sidebar"

    # Positron-specific elements
    CONSOLE_PANEL = ".positron-console"
    # Console tab in the bottom panel (shares the panel with Terminal). Used as
    # the "Positron is loaded" signal and to re-activate the console after a
    # terminal_run leaves the Terminal tab selected.
    CONSOLE_TAB = 'a.action-label[aria-label="Console"]'
    # Active console instance + its Monaco input (confirmed live; see
    # posit-dev/positron/test/e2e/pages/console.ts and exec.py).
    ACTIVE_CONSOLE = '.console-instance[style*="z-index: auto"]'
    CONSOLE_INPUT = ".console-input"
    VARIABLES_PANE = ".positron-variables"
    PLOTS_PANE = ".positron-plots"
    HELP_PANE = ".positron-help"

    # Data explorer
    DATA_EXPLORER = ".positron-data-explorer"

    # Extensions panel (same as VS Code)
    # The extensions search box is a Monaco editor, not an <input> — the old
    # `input[type='text']` selector matches nothing on Workbench 2026.04+.
    # Locator reported working on a live 2026.04 deployment in #280. Click to
    # focus, then type keystrokes; Locator.fill() rejects Monaco widgets.
    EXTENSIONS_SEARCH_INPUT = "div[data-uri='extensions:searchinput'] .view-line"

    # Posit Workbench extension
    POSIT_EXTENSION_TAB_NAME = "Posit Workbench"
    POSIT_EXTENSION_HOME_BUTTON_NAME = "home Posit Workbench"

    @staticmethod
    def extension_list_item(extension_id: str) -> str:
        """Selector for an installed extension by its ID (e.g. 'quarto.quarto')."""
        if not EXTENSION_ID_RE.match(extension_id):
            raise ValueError(f"Invalid extension ID (contains unsafe characters): {extension_id!r}")
        return f".extension-list-item[data-extension-id='{extension_id}']"
