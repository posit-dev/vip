"""Workbench page selectors.

Organized to mirror rstudio-pro/e2e/pages/ for easier translation.
Each module contains selector constants and dynamic selector methods
for a specific page or component.
"""

from .console_pane import ConsolePaneSelectors
from .homepage import Homepage, NewSessionDialog
from .ide_base import IDEBase
from .jupyterlab_session import JupyterLabSession
from .login import LoginPage
from .positron_session import PositronSession
from .rstudio_session import RStudioSession
from .vscode_session import VSCodeSession

__all__ = [
    "ConsolePaneSelectors",
    "Homepage",
    "IDEBase",
    "JupyterLabSession",
    "LoginPage",
    "NewSessionDialog",
    "PositronSession",
    "RStudioSession",
    "VSCodeSession",
]
