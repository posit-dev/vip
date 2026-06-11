"""RStudio Git pane selectors.

Selectors target the RStudio Source Control / Git pane UI.

IMPORTANT: These selectors are derived from RStudio's known DOM structure
and have NOT been validated against a live Workbench instance.  They should
be reviewed and adjusted when running against a real deployment.  Use
Playwright's DevTools or ``page.pause()`` in headed mode to verify selector
stability before relying on these in CI.
"""


class RStudioGitPane:
    """Selectors for the RStudio Git pane (Source Control tab)."""

    # The Git tab in the Environment/History/Git pane set (upper-right by default).
    # The tab label is "Git".
    GIT_TAB = "#rstudio_workbench_tab_vcs, [data-id='vcs'], button:text-is('Git')"

    # The Git pane panel container.
    GIT_PANEL = "#rstudio_workbench_panel_vcs"

    # -----------------------------------------------------------------------
    # Toolbar buttons inside the Git pane
    # -----------------------------------------------------------------------

    # "Diff" button — opens the Review Changes dialog.
    DIFF_BUTTON = "#rstudio_vcs_toolbar_diff, button[title='Diff'], button:text-is('Diff')"

    # "Commit" button in the toolbar (opens the Commit dialog).
    COMMIT_BUTTON = "#rstudio_vcs_toolbar_commit, button[title='Commit'], button:text-is('Commit')"

    # "Pull" button.
    PULL_BUTTON = "#rstudio_vcs_toolbar_pull, button[title='Pull'], button:text-is('Pull')"

    # "Push" button.
    PUSH_BUTTON = "#rstudio_vcs_toolbar_push, button[title='Push'], button:text-is('Push')"

    # -----------------------------------------------------------------------
    # File staging area (checklist of changed files)
    # -----------------------------------------------------------------------

    # Each row in the staged-file list.  Rows have an aria-label that includes
    # the filename.
    STAGED_FILE_ROW = "[class*='vcs-file-list'] tr, .rstudio_filelist tr"

    # The "Stage All" button (stages every changed file with one click).
    STAGE_ALL_BUTTON = (
        "button[title='Stage All'], button:text-is('Stage All'), [data-action='stage-all']"
    )

    # Individual stage checkbox inside a file row.  Click to stage that file.
    # RStudio uses a custom checkbox element; the selector matches the cell
    # that contains the staged/unstaged status icon.
    FILE_STAGE_CHECKBOX = ".rstudio_vcs_staged, [class*='staged'] input[type='checkbox']"

    # -----------------------------------------------------------------------
    # Commit dialog (opened by the Commit toolbar button)
    # -----------------------------------------------------------------------

    # The overall commit dialog container.
    COMMIT_DIALOG = ".rstudio_dialog_contents, [class*='commitDialog'], [role='dialog']"

    # Commit message textarea inside the dialog.
    COMMIT_MESSAGE = (
        "textarea[placeholder*='commit'], "
        "textarea[id*='commit_message'], "
        ".rstudio_commit_message textarea, "
        "textarea"
    )

    # "Commit" submit button inside the dialog.
    COMMIT_SUBMIT_BUTTON = (
        "button:text-is('Commit'), button[id*='commit_button'], .rstudio_commit_submit"
    )

    # "Push" button inside the commit dialog (appears after a successful commit).
    COMMIT_DIALOG_PUSH_BUTTON = (
        "button:text-is('Push'), button[title*='Push'], .rstudio_commit_push"
    )

    # Progress/result text area shown after commit/push completes.
    COMMIT_OUTPUT = ".rstudio_commit_output, [class*='commit-output'], [class*='gitOutput']"

    # "Close" button to dismiss the commit dialog.
    COMMIT_CLOSE_BUTTON = "button:text-is('Close'), button[data-dismiss='modal']"
