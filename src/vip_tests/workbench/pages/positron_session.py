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
    # Console tab in the bottom panel (shares the panel with Terminal). Used to
    # re-activate the console after a terminal_run leaves the Terminal tab
    # selected. Only present once a console session is running (see below).
    CONSOLE_TAB = 'a.action-label[aria-label="Console"]'
    # Positron (Workbench 2026+) opens to a Welcome page with NO auto-started
    # console: CONSOLE_PANEL / CONSOLE_TAB / ACTIVE_CONSOLE / CONSOLE_INPUT do
    # not exist until a console session is started via this button (its visible
    # text is "Start Session"; the aria-label is the stable hook). Clicking it
    # opens the interpreter quickpick. Confirmed live on dev.current (issue #477).
    START_CONSOLE_BUTTON = 'button[aria-label="Start New Console Session"]'
    # Interpreter rows in the quickpick opened by START_CONSOLE_BUTTON.
    # Interpreter discovery is asynchronous (~10s on a cold session), so callers
    # must POLL this for a populated list before selecting a row.
    INTERPRETER_QUICKPICK_ROW = (
        ".quick-input-widget .monaco-list-row, .quick-input-list .monaco-list-row"
    )
    # Active console instance + its Monaco input (confirmed live; see
    # posit-dev/positron/test/e2e/pages/console.ts and exec.py).
    ACTIVE_CONSOLE = '.console-instance[style*="z-index: auto"]'
    CONSOLE_INPUT = ".console-input"
    # Present even on the Welcome page (before any console starts), so it is a
    # console-independent "this is Positron" discriminator for _detect_ide.
    VARIABLES_PANE = ".positron-variables"
    PLOTS_PANE = ".positron-plots"
    HELP_PANE = ".positron-help"

    # Data explorer
    DATA_EXPLORER = ".positron-data-explorer"

    # Extensions panel (same as VS Code)
    # The extensions search box is a Monaco editor, not an <input> — the old
    # `input[type='text']` selector matches nothing on Workbench 2026.04+.
    # Selector taken from the reporter's live-2026.04 findings in #280; not yet
    # re-validated by VIP. Click to focus, then type; fill() rejects Monaco.
    EXTENSIONS_SEARCH_INPUT = "div[data-uri='extensions:searchinput'] .view-line"

    # Posit Workbench extension
    POSIT_EXTENSION_TAB_NAME = "Posit Workbench"
    POSIT_EXTENSION_HOME_BUTTON_NAME = "home Posit Workbench"

    @staticmethod
    def extension_list_item(extension_id: str) -> str:
        """Selector for an installed extension by its ID (e.g. 'quarto.quarto').

        ``data-extension-id`` is carried on the outer ``.monaco-list-row``; the
        nested ``.extension-list-item`` div does not have it, so a combined
        ``.extension-list-item[data-extension-id=...]`` never matches (verified
        on VS Code web 1.105.1, issue #280).
        """
        if not EXTENSION_ID_RE.match(extension_id):
            raise ValueError(f"Invalid extension ID (contains unsafe characters): {extension_id!r}")
        return f".monaco-list-row[data-extension-id='{extension_id}']"
