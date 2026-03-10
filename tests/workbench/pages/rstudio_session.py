"""RStudio session selectors.

Mirrors: rstudio-pro/e2e/pages/rstudio_session.page.ts
"""


class RStudioSession:
    """Selectors for the RStudio IDE."""

    # Core UI elements
    LOGO = "#rstudio_rstudio_logo"
    CONTAINER = "#rstudio_container"

    # Project menu
    PROJECT_MENU = "#rstudio_project_menubutton_toolbar"
    PROJECT_MENU_CLOSE = "#rstudio_label_close_project_command"

    # Panes
    ENVIRONMENT_PANE = "#rstudio_workbench_panel_environment"
    TAB_SET_2_PANE = "#rstudio_TabSet2_pane"

    # R version menu
    R_VERSION_MENU = "#rstudio_versions_popup_menu"
    R_VERSION_MENU_ITEMS = ".rstudio_versions_popup_value"
    R_VERSION_CHECKED = "[class*=rstudio_versions_popup_checked]"
    R_VERSION_NEXT = (
        "//tr[child::*[contains(@class, 'rstudio_versions_popup_checked')]]"
        "/following-sibling::*[1]//*[contains(@class,'rstudio_versions_popup_value')]"
    )
