"""Login page selectors.

Mirrors: rstudio-pro/e2e/pages/login.page.ts
"""


class LoginPage:
    """Selectors for the Workbench login page."""

    USERNAME = "#username"
    PASSWORD = "#password"
    BUTTON = "#signinbutton"
    STAY_SIGNED_IN = "#staySignedIn"
    ERROR_PANEL = "#errorpanel"
    ERROR_TEXT = "#errortext"
