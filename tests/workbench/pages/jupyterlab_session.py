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
