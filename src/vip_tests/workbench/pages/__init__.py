"""Workbench page selectors.

Organized to mirror rstudio-pro/e2e/pages/ for easier translation.
Each module contains selector constants and dynamic selector methods
for a specific page or component.
"""

from .console_pane import ConsolePaneSelectors
from .homepage import (
    Homepage,
    Homepage_2026_05,
    NewSessionDialog,
    get_homepage,
    get_new_session_dialog_close_strategy,
)
from .ide_base import IDEBase
from .jupyterlab_session import JupyterLabSession
from .login import LoginPage
from .positron_session import PositronSession
from .rstudio_session import RStudioSession
from .vscode_session import VSCodeSession

__all__ = [
    "ConsolePaneSelectors",
    "Homepage",
    "Homepage_2026_05",
    "IDEBase",
    "JupyterLabSession",
    "LoginPage",
    "NewSessionDialog",
    "PositronSession",
    "RStudioSession",
    "VSCodeSession",
    "get_homepage",
    "get_new_session_dialog_close_strategy",
]
