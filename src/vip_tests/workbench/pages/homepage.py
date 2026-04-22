"""Homepage selectors.

Mirrors: rstudio-pro/e2e/pages/homepage.page.ts
"""


class NewSessionDialog:
    """Selectors for the new session dialog."""

    DIALOG = "[role='dialog']"
    TITLE = "[data-slot='dialog-title']"
    SESSION_NAME = "input#rstudio_label_session_name"
    JOIN_CHECKBOX = "#modal-auto-join-button"
    LAUNCH_BUTTON = "button:text-is('Launch')"
    CANCEL_BUTTON = "#modalCancelBtn"

    # Resource configuration
    CPU_INPUT = "#rstudio_label_cpus"
    CPU_REQUEST = "#rstudio_label_cpu_request"
    MEMORY_INPUT = "#rstudio_group_memory input"
    MEMORY_REQUEST = "#rstudio_label_memory_request"
    CLUSTER_DROPDOWN = "#rstudio_label_cluster"
    RESOURCE_PROFILE = "#rstudio_label_resource_profile"
    QUEUE_DROPDOWN = "#rstudio_label_queue"
    IMAGE_DROPDOWN = "#rstudio_label_image"
    IMAGE_EDIT_BUTTON = "#rstudio_group_image button"

    # IDE icons (legacy modal)
    RSTUDIO_PRO_ICON = "[id*=trigger-RStudio]"
    VSCODE_ICON = ".rstudio-modal [title='New VS Code session']"
    JUPYTERLAB_ICON = ".rstudio-modal [title='New JupyterLab session']"
    POSITRON_ICON = "//button[@aria-label='New Positron Pro session']//div[text()='Preview']"

    # Managed credentials
    SNOWFLAKE_WIDGET = "[aria-label='Snowflake Credential Selection']"
    DATABRICKS_WIDGET = "[aria-label='Databricks Credential Selection']"
    DATABRICKS_DROPDOWN = "#rstudio_group_databricks_workspace #rstudio_label_databricks_workspace"
    AWS_CREDENTIAL_BTN = "#aws-credential-selection"
    DATABRICKS_CREDENTIAL_BTN = "#databricks-credential-selection"

    # IDE name mapping for display names in tabs
    IDE_DISPLAY_NAMES = {
        "RStudio": "RStudio Pro",
        "VS Code": "VS Code",
        "JupyterLab": "JupyterLab",
        "Positron": "Positron",
    }

    @staticmethod
    def ide_tab(ide_type: str) -> str:
        """Selector for IDE tab trigger by type."""
        # Remove spaces for the ID format (e.g., "RStudio Pro" -> "RStudioPro")
        return f"[id*='trigger-{ide_type.replace(' ', '')}']"

    @staticmethod
    def ide_display_name(ide_type: str) -> str:
        """Get the display name for an IDE type in the new session dialog."""
        return NewSessionDialog.IDE_DISPLAY_NAMES.get(ide_type, ide_type)

    @staticmethod
    def cluster_option(option: str) -> str:
        """Selector for cluster dropdown option."""
        return f"[role='option'][name='{option}']"

    @staticmethod
    def resource_profile_option(option: str) -> str:
        """Selector for resource profile dropdown option."""
        return f"[role='option'][name='{option}']"


class Homepage:
    """Selectors for the Workbench homepage."""

    # Header
    POSIT_LOGO = "#posit-logo"
    POSIT_TITLE = "#posit-title"
    CURRENT_USER = "#current-user"
    SIGN_OUT_FORM = "form[action*='sign-out']"
    SIGN_OUT_BTN_OLD = "#signOutBtn"

    # Navigation
    PROJECTS_TAB = "a:text-is('Projects')"
    JOBS_TAB = "a:text-is('Jobs')"
    SETTINGS_LINK = "//a[text()=' Settings']"

    # Session actions
    NEW_SESSION_BUTTON = "button:text-is('New Session')"
    NEW_SESSION_BUTTON_EMPTY = "button:text-is('New Session')"  # Second instance on empty state
    QUIT_BUTTON = "button:text-is('Quit')"
    QUIT_ALL_BUTTON = "button:text-is('Quit All')"
    SUSPEND_BUTTON = "button:text-is('Suspend')"
    SUSPEND_ALL_BUTTON = "#suspendAllBtn"

    # Session list
    SESSION_LIST = "#sessionsList"
    TOP_SESSION = "tbody > tr:first-of-type"
    TOP_SESSION_LINK = "tbody > tr:first-of-type > td:nth-of-type(3) div div a"
    NO_PROJECTS = "text=No projects"

    # Project actions
    NEW_PROJECT_BUTTON = "#newProjectBtn"
    OPEN_PROJECT_BUTTON = "#openProjectBtn"
    DELETE_PROJECT_BUTTON = "button:text-is('Remove')"
    PROJECT_LIST = "#projectsList"

    # Dialogs
    CONFIRM_QUIT = "#modalOkBtn"
    FORCE_QUIT = "[data-testid='force-quit-session-button']"
    CONFIRM_FORCE_QUIT = "[data-testid='confirm-force-quit-button']"
    SESSION_DETAILS_HEADER = "[data-slot='dialog-title']"
    SESSION_DETAILS_DIALOG = "[class*='modal-dialog']"

    # Settings page
    SETTINGS_HEADER = "h1:has-text('Settings')"
    MANAGED_CREDENTIALS_LINK = "//a[text()='Managed Credentials']"
    MANAGED_CREDENTIALS_HEADER = "h2:has-text('Managed Credentials')"

    # Homepage modes
    SWITCH_TO_LEGACY = "button:text-is('Switch to Legacy Homepage')"
    SWITCH_TO_NEW = "a:text-is('Switch to new homepage')"

    # Footer
    FOOTER_POSIT_LINK = "a:text-is('Posit Workbench')"

    @staticmethod
    def session_link(name: str) -> str:
        """Selector for session link by name."""
        return f"a[title='{name}'], a:text-is('{name}')"

    @staticmethod
    def session_checkbox(name: str) -> str:
        """Selector for session selection checkbox."""
        return f"[aria-label='select {name}']"

    @staticmethod
    def session_text(name: str) -> str:
        """Selector for session name text."""
        return f"text='{name}'"

    @staticmethod
    def session_status(name: str) -> str:
        """Selector for session status by session name (XPath)."""
        return f"//*[text()='{name}']//..//..//..//..//td[8]//div"

    @staticmethod
    def session_details_button(name: str) -> str:
        """Selector for session details button by session name."""
        return (
            f"//a[contains(text(), '{name}')]"
            f"//..//..//..//..//td[contains(@data-testid, 'cell-actions')]/button"
        )

    @staticmethod
    def session_rename_button(name: str) -> str:
        """Selector for session rename button."""
        return f"tr[aria-label$='{name}'] button[aria-label='Rename session']"

    @staticmethod
    def session_state(state: str) -> str:
        """Selector for session state button (Starting, Active, etc.)."""
        return f"button:text-is('{state}')"

    @staticmethod
    def session_row(name: str) -> str:
        """Selector for session row by session name using aria-label.

        Workbench sets aria-label to e.g. "No project: <session_name>",
        so match with ends-with ($=) to anchor on the session name and
        avoid strict-mode collisions when one name is a substring of another.
        """
        return f"tr[aria-label$='{name}']"

    @staticmethod
    def session_row_status(name: str, status: str) -> str:
        """Selector for session row with specific status.

        Finds the row containing the session name, then matches if
        that row's status cell contains the given status.
        """
        return f"tr[aria-label$='{name}'] div[aria-label='{status}']"
