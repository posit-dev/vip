"""VS Code session selectors.

Mirrors: rstudio-pro/e2e/pages/vscode_session.page.ts
"""

from vip_tests.workbench.pages._extensions import EXTENSION_ID_RE

__all__ = ["EXTENSION_ID_RE", "VSCodeSession"]


class VSCodeSession:
    """Selectors for the VS Code IDE."""

    # Core UI elements
    WORKBENCH = ".monaco-workbench"
    STATUS_BAR = ".statusbar"
    ACTIVITY_BAR = ".activitybar"
    SIDEBAR = ".sidebar"
    EDITOR_AREA = ".editor-container"

    # Title bar
    TITLE_BAR = ".titlebar"

    # Terminal
    TERMINAL_PANEL = ".terminal"
    TERMINAL_INPUT = ".xterm-helper-textarea"

    # Python / R Interactive Window (REPL output panel, DOM-rendered)
    # Used by vscode_eval for reliable output capture without xterm scraping.
    REPL_INPUT = ".interactive-input-widget textarea"
    REPL_OUTPUT = ".interactive-output-widget"

    # Command palette — used to open the Interactive Window when absent
    COMMAND_PALETTE_INPUT = ".quick-input-box input"

    # Extensions panel
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
