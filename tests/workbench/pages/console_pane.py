"""Console pane selectors.

Mirrors: rstudio-pro/e2e/pages/console_pane.page.ts
"""


class ConsolePaneSelectors:
    """Selectors for the RStudio console pane."""

    # Console tab and input/output
    TAB = "#rstudio_workbench_tab_console"
    INPUT = "#rstudio_console_input"
    OUTPUT = "#rstudio_workbench_panel_console"
    OUTPUT_ELEMENT = "#rstudio_console_output"
    SHELL = "#rstudio_shell_widget"

    # Output lines (XPath for last elements)
    OUTPUT_LAST = "(//*[@id='rstudio_console_output']/span)[last()]"
    OUTPUT_LAST_LINE = "(//*[@id='rstudio_console_output']/span)[last()]/span[last()]"

    # Console buttons
    CLEAR_BTN = "[id^='rstudio_tb_consoleclear']"
    CLEAR_BTN_DESKTOP = "#rstudio_tb_consoleclear_0"
    INTERRUPT_R_BTN = "[id^='rstudio_tb_interruptr']"

    # Traceback
    TRACEBACK_BTN = "[class*='show_traceback_text']"
    STACK_TRACE = "[class*='stack_trace']"

    # Session status
    SESSION_SUSPENDED_ICON = "#r_session_suspended_console"
    SESSION_CANNOT_SUSPEND_ICON = "[title*='suspend']"

    # R version display
    R_VERSION = "#rstudio_console_interpreter_version"
    R_VERSION_TABBED = "#rstudio_console_interpreter_version_tabbed"

    # Console layout controls
    MINIMIZE_BTN = "[aria-label='Minimize Console']"
    MAXIMIZE_BTN = "[aria-label='Maximize Console']"
    RESTORE_BTN = "[aria-label='Restore Console']"

    # Python indicator
    PYTHON_ICON = "#g1894"
