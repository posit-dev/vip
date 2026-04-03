"""Positron session selectors.

Mirrors: rstudio-pro/e2e/pages/positron_session.page.ts
"""


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
    VARIABLES_PANE = ".positron-variables"
    PLOTS_PANE = ".positron-plots"
    HELP_PANE = ".positron-help"

    # Data explorer
    DATA_EXPLORER = ".positron-data-explorer"
