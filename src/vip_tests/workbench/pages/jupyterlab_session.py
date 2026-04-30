"""JupyterLab session selectors.

Mirrors: rstudio-pro/e2e/pages/jupyterlab_session.page.ts
"""


class JupyterLabSession:
    """Selectors for the JupyterLab IDE."""

    # Core UI elements
    LAUNCHER = ".jp-Launcher"
    NOTEBOOK_PANEL = ".jp-NotebookPanel"
    MAIN_AREA = ".jp-MainAreaWidget"

    # Sidebar
    FILE_BROWSER = ".jp-FileBrowser"
    SIDEBAR_LEFT = ".jp-SideBar.jp-mod-left"

    # Menu bar
    MENU_BAR = ".jp-MenuBar"

    # Notebook elements
    CELL = ".jp-Cell"
    CODE_CELL = ".jp-CodeCell"
    MARKDOWN_CELL = ".jp-MarkdownCell"
    CELL_INPUT = ".jp-InputArea-editor"
    CELL_OUTPUT = ".jp-OutputArea-output"

    # Toolbar
    TOOLBAR = ".jp-Toolbar"
    RUN_BUTTON = "button[data-command='notebook:run-cell-and-select-next']"

    # Launcher cards (to open a new notebook from the launcher)
    LAUNCHER_CARD = ".jp-LauncherCard"
    LAUNCHER_NOTEBOOK_CARD = ".jp-LauncherCard[data-category='Notebook']"

    # Extension Manager
    EXTENSION_MANAGER_TAB = ".jp-SideBar .lm-TabBar-tab[data-id='extensionmanager.main-view']"
    EXTENSION_SEARCH_INPUT = ".jp-extensionmanager-search input"

    # Posit Workbench extension
    POSIT_EXTENSION_ICON = "#rsw-icon"

    @staticmethod
    def installed_extension_item(name: str) -> str:
        """Selector for an installed extension entry by name.

        Targets the 'Installed' section of the Extension Manager to avoid
        matching extensions that are merely available but not installed.
        Uses Playwright's text= selector to avoid CSS quoting issues.
        """
        # Escape any regex-special characters so the name matches literally
        import re

        escaped = re.escape(name)
        return f".jp-extensionmanager-installedlist .jp-extensionmanager-entry >> text=/{escaped}/i"
