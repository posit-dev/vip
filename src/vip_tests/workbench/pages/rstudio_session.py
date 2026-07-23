"""RStudio session selectors.

These mirror the RStudio Pro e2e page objects under rstudio-pro/e2e (the
Workbench Jobs selectors correspond to its Launcher pane and IDE modal page
objects). Treat them as structural references, not a 1:1 copy, and verify
against the live IDE DOM when RStudio Pro builds shift element IDs.
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

    # Workbench Jobs pane (Launcher jobs, separate from Background Jobs).
    # Verified against Workbench 2026.07.0 (RStudio Pro) over CDP.
    #
    # The tab and panel IDs use "workbench_jobs" (underscore) on current builds;
    # the prior no-underscore "workbenchjobs" form is kept as a fallback for
    # older builds in the support window. Only the two exact IDs are used --
    # a substring match like [id*='workbench_jobs'] would also match the panel
    # ("rstudio_workbench_panel_workbench_jobs"), so the tab locator would
    # resolve to two elements and trip Playwright strict mode.
    WORKBENCH_JOBS_PANEL = (
        "#rstudio_workbench_panel_workbench_jobs, #rstudio_workbench_panel_workbenchjobs"
    )
    WORKBENCH_JOBS_TAB = (
        "#rstudio_workbench_tab_workbench_jobs, #rstudio_workbench_tab_workbenchjobs, "
        "button:text-is('Workbench Jobs')"
    )
    # The "new job" toolbar button is #rstudio_tb_startworkbenchjob, labeled
    # "Start Workbench Job" on current builds (was "Run Script as Workbench Job"
    # on older builds -- kept as a text fallback).
    WORKBENCH_JOB_NEW_BUTTON = (
        "#rstudio_tb_startworkbenchjob, button:text-is('Start Workbench Job'), "
        "button:text-is('Run Script as Workbench Job')"
    )
    # The "Run Script as Workbench Job" dialog's script-path field
    # (#rstudio_tbb_text_pro_job_script) is a readonly FileChooserTextBox on
    # Launcher deployments -- it CANNOT be typed into. The script is chosen via
    # its adjacent "Browse..." button (#rstudio_tbb_button_pro_job_script),
    # which opens a "Choose File" dialog. Verified live over CDP against
    # Workbench 2026.07.0, and in rstudio-pro source (FileChooserTextBox is
    # constructed readOnly=true unless browseButtonDisabled, which is only true
    # for local-launcher sessions without path mapping -- readonly since 2021).
    WORKBENCH_JOB_SCRIPT_INPUT = "#rstudio_tbb_text_pro_job_script"
    WORKBENCH_JOB_SCRIPT_BROWSE_BUTTON = (
        "#rstudio_tbb_button_pro_job_script, "
        "#rstudio_tbb_text_pro_job_script ~ button:has-text('Browse')"
    )
    # The "Choose File" dialog opened by the Browse button. Its name field is a
    # real editable input; typing a filename + clicking Open populates the
    # readonly script box above. The file must already exist or Open is rejected.
    FILE_CHOOSER_NAME_INPUT = "#file_dialog_name_prompt"
    FILE_CHOOSER_OPEN_BUTTON = "#rstudio_file_accept_open, button:text-is('Open')"
    FILE_CHOOSER_CANCEL_BUTTON = "#rstudio_file_cancel_open, button:text-is('Cancel')"

    # The submission dialog's OK button (#rstudio_dlg_ok) is captioned "Start"
    # ("Submit" kept as a text fallback for older builds).
    WORKBENCH_JOB_SUBMIT_BUTTON = (
        "#rstudio_dlg_ok, button:text-is('Start'), button:text-is('Submit')"
    )

    # Job status (shared between Background and Workbench Jobs).
    #
    # On the Workbench Jobs (Launcher) panel the completed status renders as a
    # single leaf DIV whose text fuses the word and a timestamp, e.g.
    # "Succeeded 4:25 PM", inside a GWT-obfuscated class (not "job-status").
    # An exact-match (:text-is('Succeeded')) or span-only selector therefore
    # never matches, so job completion polling timed out at the full job
    # timeout even though the job succeeded. ``:text('Succeeded')`` selects the
    # smallest element *containing* the substring on any tag, matching that
    # fused leaf. Verified live over CDP against Workbench 2026.07.0. The prior
    # exact/span selectors are kept as fallbacks for the Background Jobs panel
    # and older builds.
    JOB_STATUS_SUCCEEDED = (
        "*:text('Succeeded'), *:text('Completed'), "
        "span:text-is('Succeeded'), span:text-is('Completed'), "
        "[class*='job-status']:text-is('Succeeded')"
    )
    JOB_OUTPUT_AREA = "[class*='job-output'], [id*='job_output'], [class*='Jobs'] [class*='output']"
