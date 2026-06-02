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

    # Background Jobs pane (Console pane tab set)
    BACKGROUND_JOBS_TAB = "#rstudio_workbench_tab_jobs"
    BACKGROUND_JOBS_PANEL = "#rstudio_workbench_panel_jobs"
    BACKGROUND_JOBS_START_BUTTON = (
        "button[title='Start Background Job'], button:text-is('Start Background Job')"
    )
    BACKGROUND_JOB_SCRIPT_INPUT = "input[placeholder*='script'], input[id*='script']"
    BACKGROUND_JOB_RUN_BUTTON = "button:text-is('Start'), button[id*='start']"

    # Workbench Jobs pane (Launcher jobs, separate from Background Jobs)
    WORKBENCH_JOBS_PANEL = "#rstudio_workbench_panel_workbenchjobs"
    WORKBENCH_JOBS_TAB = "[id*='workbenchjobs'], button:text-is('Workbench Jobs')"
    WORKBENCH_JOB_NEW_BUTTON = (
        "button[title='Run Script as Workbench Job'], button:text-is('Run Script as Workbench Job')"
    )
    WORKBENCH_JOB_SUBMIT_BUTTON = "button:text-is('Submit')"

    # Job status (shared between Background and Workbench Jobs)
    JOB_STATUS_SUCCEEDED = (
        "span:text-is('Succeeded'), span:text-is('Completed'), "
        "[class*='job-status']:text-is('Succeeded')"
    )
    JOB_OUTPUT_AREA = "[class*='job-output'], [id*='job_output'], [class*='Jobs'] [class*='output']"
