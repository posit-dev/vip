"""Homepage selectors.

Mirrors: rstudio-pro/e2e/pages/homepage.page.ts
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from playwright.sync_api import Page

from vip.version import ProductVersion

_T = TypeVar("_T")


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

    # Runtime version selectors
    R_VERSION_DROPDOWN = "#rstudio_label_r_version"
    PYTHON_VERSION_DROPDOWN = "#rstudio_label_python_version"

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
    # Workbench 2026.05.0 appends the selected-session count to the Quit button
    # label (e.g. "Quit (1)") instead of plain "Quit". Match both the old exact
    # "Quit" and the new "Quit (N)" forms with a comma-separated selector,
    # mirroring the cross-version pattern in session_row_status. The has-text
    # "Quit (" clause matches any count while excluding the separate "Quit All"
    # button. (Avoids a :text-matches regex, whose backslashes must be doubled
    # to survive Playwright's selector parser -- an easy footgun.)
    QUIT_BUTTON = "button:text-is('Quit'), button:has-text('Quit (')"
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

        Finds the row containing the session name, then matches that row's
        status indicator for the given status.

        Workbench rendered the status differently across versions: before
        2026.06 it was a ``div[aria-label='<status>']``; on 2026.06 it is a
        button whose accessible name is the status word (sourced from either
        its text or an ``aria-label``).  Match any of these forms with a
        comma-separated selector so status checks survive the UI change.
        """
        row = f"tr[aria-label$='{name}']"
        return (
            f"{row} div[aria-label='{status}'], "
            f"{row} button[aria-label='{status}'], "
            f"{row} button:text-is('{status}')"
        )


class Homepage_2026_05(Homepage):  # noqa: N801 - version-embedded name matches design convention
    """Homepage selectors for the 2026.05 shadcn redesign onward.

    ``SESSION_DETAILS_DIALOG`` is the one confirmed selector-only delta in
    this file: baseline ``Homepage`` still targets the legacy Bootstrap-style
    ``[class*='modal-dialog']`` container, which does not match the shadcn
    ``data-slot``-based dialog markup shipped from 2026.05 onward (see the
    workaround note in ``test_sessions.py::resume_suspended_session``, which
    currently targets the stable "Launch" button text instead of the
    container for exactly this reason). Every other selector already reads
    correctly on both old and new markup (either unchanged, or already
    unioned like ``QUIT_BUTTON`` / ``session_row_status``), so nothing else
    needs to be overridden here.
    """

    SESSION_DETAILS_DIALOG = "[data-slot='dialog-content']"


# Resolution table for get_homepage(): (minimum version, page-object class),
# sorted ascending by threshold. The class for the highest threshold that is
# <= the detected version wins; versions below the lowest threshold (or an
# unparseable/None version) fall back to the oldest class. Single-sided
# thresholds only -- no version ranges/max_version (see design doc scope cut).
_HOMEPAGE_VERSIONS: list[tuple[ProductVersion, type[Homepage]]] = [
    (ProductVersion("2026.05.0"), Homepage_2026_05),
]


def _resolve_by_version(
    version: ProductVersion | str | None,
    table: list[tuple[ProductVersion, _T]],
    oldest: _T,
) -> _T:
    """Return the table entry for the highest threshold <= *version*.

    Shared resolution logic for both the page-object factory
    (``get_homepage``) and the behavior-strategy lookup
    (``get_new_session_dialog_close_strategy``): both are UI-resolution
    concerns rather than test-gating, so an unparseable or missing version
    falls back to *oldest* instead of raising (unlike the pytest marker path
    in ``plugin.py``, there is no "skip" concept here).
    """
    if version is None:
        return oldest
    if isinstance(version, str):
        try:
            version = ProductVersion(version)
        except ValueError:
            return oldest

    resolved = oldest
    for threshold, value in table:
        if version >= threshold:
            resolved = value
        else:
            break
    return resolved


def get_homepage(version: ProductVersion | str | None) -> type[Homepage]:
    """Return the ``Homepage`` subclass matching the deployed Workbench version.

    Accepts ``None`` or an unparseable string and falls back to the oldest
    known class (``Homepage``) -- page-object selection is a UI concern, not
    test gating, so there's no skip path here.
    """
    return _resolve_by_version(version, _HOMEPAGE_VERSIONS, Homepage)


# ---------------------------------------------------------------------------
# New Session dialog close behavior (Escape vs. Cancel button)
# ---------------------------------------------------------------------------
#
# Unlike SESSION_DETAILS_DIALOG above, the 2026.05 shadcn redesign changed how
# the New Session dialog is dismissed: the legacy `#modalCancelBtn` (see
# `NewSessionDialog.CANCEL_BUTTON`, still used by existing step files) does
# not exist in the new dialog at all -- pressing Escape closes it instead.
# That's a BEHAVIOR difference, not a selector difference, so it can't be
# expressed as a page-object override; it needs a strategy dict keyed by
# version, mirroring idp.py's `_IDP_STRATEGIES` but keyed by version
# threshold instead of a flat IdP name.
#
# These strategies are not wired into any step file yet (issue #409's job)
# -- this only builds the resolution mechanism and its own selftest.


def _close_dialog_via_cancel_button(page: Page) -> None:
    """Dismiss the New Session dialog via the legacy Cancel button (pre-2026.05)."""
    page.locator(NewSessionDialog.CANCEL_BUTTON).click()


def _close_dialog_via_escape(page: Page) -> None:
    """Dismiss the New Session dialog by pressing Escape (2026.05 shadcn onward)."""
    page.keyboard.press("Escape")


_NEW_SESSION_DIALOG_CLOSE_STRATEGIES: list[tuple[ProductVersion, Callable[[Page], None]]] = [
    (ProductVersion("2026.05.0"), _close_dialog_via_escape),
]


def get_new_session_dialog_close_strategy(
    version: ProductVersion | str | None,
) -> Callable[[Page], None]:
    """Return the function that dismisses the New Session dialog for *version*.

    Same fallback policy as ``get_homepage``: ``None`` or an unparseable
    string resolves to the oldest known strategy (the legacy Cancel button)
    rather than raising.
    """
    return _resolve_by_version(
        version, _NEW_SESSION_DIALOG_CLOSE_STRATEGIES, _close_dialog_via_cancel_button
    )
