"""JupyterLab session selectors.

Mirrors: rstudio-pro/e2e/pages/jupyterlab_session.page.ts
"""

import re


class JupyterLabSession:
    """Selectors for the JupyterLab IDE."""

    # Core UI elements
    # The JupyterLab application shell — present on every load regardless of the
    # active view, so it is the reliable "JupyterLab is up" readiness signal.
    # (`.jp-Launcher` only exists while the Launcher tab is open, which some
    # deployments do not auto-open — see issue #478.)
    SHELL = ".jp-LabShell"
    # Boot splash overlay; lingers after SHELL mounts and intercepts clicks
    # until the app finishes hydrating, so wait for it to clear before
    # interacting (issue #478).
    SPLASH = "#jupyterlab-splash"
    LAUNCHER = ".jp-Launcher"
    NOTEBOOK_PANEL = ".jp-NotebookPanel"
    MAIN_AREA = ".jp-MainAreaWidget"
    # Modal dialog (e.g. "Select Kernel" for a new notebook) and its accept button.
    DIALOG = ".jp-Dialog"
    DIALOG_ACCEPT = ".jp-Dialog .jp-Dialog-button.jp-mod-accept"

    # Kernel execution-status indicator on the notebook toolbar. JupyterLab sets
    # its ``data-status`` to "idle" once the kernel is connected and ready, and
    # "busy" while a cell is running. Gating the first cell run on "idle" avoids
    # typing/running before the kernel has finished connecting, which drops the
    # input and produces the spurious "kernel did not produce output" timeout.
    KERNEL_STATUS = ".jp-Notebook-ExecutionIndicator"
    KERNEL_STATUS_IDLE = ".jp-Notebook-ExecutionIndicator[data-status='idle']"

    # Current (active) notebook tab in the dock area. Its label text is the
    # notebook's filename (e.g. "Untitled.ipynb"), used to build the contents-API
    # path for teardown deletion.
    CURRENT_TAB_LABEL = ".lm-DockPanel-tabBar .lm-TabBar-tab.jp-mod-current .lm-TabBar-tabLabel"

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

    # JupyterLab's built-in "New Launcher" command control — used to open a
    # Launcher tab on deployments that do not auto-open one (issue #478). The
    # ``:visible`` filter picks the clickable toolbar/menu control over any
    # hidden duplicate registered for the same command.
    LAUNCHER_CREATE_COMMAND = '[data-command="launcher:create"]:visible'

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
        escaped = re.escape(name)
        return f".jp-extensionmanager-installedlist .jp-extensionmanager-entry >> text=/{escaped}/i"
