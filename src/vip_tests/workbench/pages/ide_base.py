"""Base IDE selectors shared across all IDE types.

Mirrors: rstudio-pro/e2e/pages/ide_base.page.ts
"""


class IDEBase:
    """Selectors common to all IDEs when running inside Workbench."""

    # Session controls (in IDE header)
    SIGN_OUT_BTN = "[title='Sign out']"
    QUIT_SESSION_BTN = "#rstudio_tb_quitsession"
    WORKBENCH_HOME_BTN = "button[title='Posit Workbench']"

    # Tab sets (RStudio layout)
    TAB_SET_1 = "[aria-label='TabSet1']"
    TAB_SET_2 = "[aria-label='TabSet2']"

    # Session dialogs
    NEW_R_SESSION_BTN = "[aria-label='Open a new R session']"
    POPUP_PANEL = "[class*=PopupPanel]"
    DIALOG_BOX = "[class*=DialogBox]"
    DIALOG_ACTION_BTN = "[class*=DialogBox] button"

    # Save workspace dialog
    DONT_SAVE_BTN = "#rstudio_dlg_no"
    SAVE_BTN = "#rstudio_dlg_yes"

    # Modal dialogs
    QUIT_R_SESSION_MODAL = "div.gwt-DialogBox[aria-label='Quit R Session']"
    SAVE_WORKSPACE_MODAL = "div.gwt-DialogBox[aria-label='Save Current Workspace']"
    REQUIRED_PACKAGES_MODAL = "div.gwt-DialogBox[aria-label='Install Required Packages']"

    # Toasts
    CLOSING_PROJECT_TOAST = "//div[text()='Closing project...']"

    # Managed credentials
    MANAGED_CREDENTIALS_BTN = "[title='Workbench-managed Credentials']"
