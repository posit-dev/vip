# rstudio-pro to VIP Test Translation Guide

This document provides guidance for translating Workbench tests from the
rstudio-pro TypeScript Playwright suite to VIP's Python Playwright BDD framework.

## Overview

| Aspect | rstudio-pro | VIP |
|--------|-------------|-----|
| Language | TypeScript | Python |
| Framework | @playwright/test | pytest + pytest-bdd |
| Test format | Plain tests with describe/test | BDD feature files + step definitions |
| Page objects | Class per page (locators + methods) | `pages/` module with class per page + fixture factories |
| Actions | Separate action classes | Helper functions + fixtures |
| Assertions | `expect(locator).toBeVisible()` | `expect(locator).to_be_visible()` |
| User management | `createUser()` per test | Shared credentials from config |

---

## Structural Differences

### rstudio-pro: Page Object + Actions Pattern

```
pages/
  homepage.page.ts      # Locators only
  ide_base.page.ts
  console_pane.page.ts
actions/
  homepage.actions.ts   # Methods using page objects
  login.actions.ts
tests/
  rstudio_session.test.ts
```

Each page object holds locators, and a corresponding actions class provides
reusable methods that operate on those locators.

### VIP: Pages + Fixtures + Steps Pattern

```
tests/workbench/
  pages/                  # Selectors organized by page (mirrors rstudio-pro)
    __init__.py
    login.py              # LoginPage selectors
    homepage.py           # Homepage + NewSessionDialog selectors
    ide_base.py           # Shared IDE selectors
    rstudio_session.py    # RStudio-specific selectors
    console_pane.py       # Console pane selectors
    vscode_session.py     # VS Code selectors
    jupyterlab_session.py # JupyterLab selectors
    positron_session.py   # Positron selectors
  conftest.py             # Fixtures and helpers only
  test_auth.feature       # BDD scenarios
  test_auth.py            # Step definitions
  test_ide_launch.feature
  test_ide_launch.py
```

VIP organizes selectors in the `pages/` subpackage, mirroring rstudio-pro's structure.
Each page module contains selector constants (not Locator instances), and dynamic
selectors are static methods. Reusable operations are provided as pytest fixtures.

---

## Test Organization Translation

### rstudio-pro Test Structure

```typescript
test.describe('VSCode session tests', () => {
  test.beforeEach(async ({ page }) => {
    const user = await createUser();
    await performLogin(page, user.username, user.password);
  });

  test('Start and navigate to new VS Code session @smoke @vscode', async ({ page }) => {
    const sessionName = "Test VS Code Session";
    const homepageActions = new HomepageActions(page);
    // ... test body
  });
});
```

### VIP Equivalent

**Feature file (`test_vscode.feature`):**
```gherkin
@workbench
Feature: VS Code session management
  As a Posit Team administrator
  I want to verify VS Code sessions work correctly
  So that users can use VS Code in Workbench

  Scenario: VS Code session can be launched
    Given the user is logged in to Workbench
    When the user starts a new VS Code session
    Then the session transitions to Active state
    And the VS Code IDE is displayed
    And the session is cleaned up
```

**Step definitions (`test_vscode.py`):**
```python
from pytest_bdd import given, scenario, then, when
from tests.workbench.conftest import workbench_login
from tests.workbench.pages import Homepage, NewSessionDialog, VSCodeSession

@scenario("test_vscode.feature", "VS Code session can be launched")
def test_launch_vscode():
    pass

@given("the user is logged in to Workbench")
def user_logged_in(page, workbench_url, test_username, test_password):
    workbench_login(page, workbench_url, test_username, test_password)
    # ... verification
```

---

## Selector Translation Patterns

### TypeScript to Python Locator Syntax

| rstudio-pro (TypeScript) | VIP (Python) |
|--------------------------|--------------|
| `page.locator('#username')` | `page.locator("#username")` |
| `page.getByRole('button', { name: 'Launch' })` | `page.get_by_role("button", name="Launch")` |
| `page.getByText(sessionName)` | `page.get_by_text(session_name)` |
| `page.getByRole('link', { name: sessionName })` | `page.get_by_role("link", name=session_name)` |
| `page.locator(\`[aria-label='select ${name}']\`)` | `page.locator(f"[aria-label='select {name}']")` |

### Text Matching: `:text-is()` vs `:has-text()`

VIP uses `:text-is()` for exact matching. This is critical.

```python
# WRONG - partial match, may match "Create new session"
NEW_SESSION_BUTTON = "button:has-text('New Session')"

# CORRECT - exact match
NEW_SESSION_BUTTON = "button:text-is('New Session')"
```

### Page Object Translation

Both rstudio-pro and VIP organize selectors by page, but with key differences:

**rstudio-pro:** Stores `Locator` instances (requires `page` in constructor)
```typescript
// login.page.ts
export class LoginPage {
    readonly username: Locator;
    constructor(page: Page) {
        this.username = page.locator('#username');
    }
}
```

**VIP:** Stores selector strings (no `page` needed, more flexible)
```python
# pages/login.py
class LoginPage:
    USERNAME = "#username"
    PASSWORD = "#password"
    BUTTON = "#signinbutton"
```

**Translation mapping:**

| rstudio-pro file | VIP file |
|------------------|----------|
| `pages/login.page.ts` | `pages/login.py` |
| `pages/homepage.page.ts` | `pages/homepage.py` |
| `pages/ide_base.page.ts` | `pages/ide_base.py` |
| `pages/rstudio_session.page.ts` | `pages/rstudio_session.py` |
| `pages/console_pane.page.ts` | `pages/console_pane.py` |
| `pages/vscode_session.page.ts` | `pages/vscode_session.py` |

**Dynamic selectors use static methods:**
```python
# pages/homepage.py
class Homepage:
    QUIT_BUTTON = "button:text-is('Quit')"

    @staticmethod
    def session_checkbox(name: str) -> str:
        return f"[aria-label='select {name}']"
```

**Usage in tests:**
```python
from tests.workbench.pages import Homepage, LoginPage, RStudioSession

# Use class attributes directly
page.locator(LoginPage.USERNAME).fill(username)
page.locator(Homepage.NEW_SESSION_BUTTON).click()
expect(page.locator(RStudioSession.LOGO)).to_be_visible()

# Dynamic selectors
page.locator(Homepage.session_checkbox(session_name)).click()
```

---

## Assertion Translation

### TypeScript Playwright Assertions

```typescript
await expect(homepage.currentUser).toBeVisible({ timeout: 10_000 });
await expect(homepage.currentUser).toHaveText(user.username, { timeout: 10_000 });
await expect(page.getByRole("button", { name: "Active" })).toBeVisible({ timeout: 60_000 });
await expect(homepage.sessionByNameLink(sessionName)).not.toBeVisible({ timeout: 30_000 });
await expect(console.consoleOutput).toContainText('[1] 4', { timeout: 10_000 });
```

### Python Playwright Assertions

```python
from playwright.sync_api import expect

expect(page.locator(Homepage.CURRENT_USER)).to_be_visible(timeout=10000)
expect(page.locator(Homepage.CURRENT_USER)).to_have_text(test_username)
expect(page.get_by_role("button", name="Active").first).to_be_visible(timeout=60000)
expect(page.locator(Homepage.session_link(session_name))).not_to_be_visible(timeout=30000)
expect(console_output).to_contain_text("[1] 4", timeout=10000)
```

**Key differences:**
- Snake_case method names (`to_be_visible` not `toBeVisible`)
- `timeout` is a keyword argument (no braces)
- Use `.first` instead of `.first()` for getting first match
- Use `not_to_be_visible()` instead of `not.toBeVisible()`

---

## Action Translation Patterns

### rstudio-pro Action Classes

```typescript
// homepage.actions.ts
export class HomepageActions {
  async startNewSession(options: {
    sessionType: 'RStudio' | 'VS Code';
    autoJoin?: boolean;
    sessionName?: string;
  }): Promise<void> {
    await this.homepage.newSessionBtn.click();
    await this.homepage.getIDEForNewSessionElement(sessionType).click();
    // ...
  }

  async quitSessionByName(sessionName: string): Promise<void> {
    await this.clickOnSessionCheckbox(sessionName);
    await this.homepage.quitButton.click();
    await expect(this.homepage.sessionByNameText(sessionName)).not.toBeVisible();
  }
}
```

### VIP Fixture Factories

```python
# conftest.py
@pytest.fixture
def wb_start_session(page: Page, wb_login):
    """Factory fixture to start a session of any IDE type."""

    def _start(ide_type: str, session_name: str | None = None, *, auto_join: bool = True) -> str:
        if session_name is None:
            session_name = f"VIP Test {ide_type} {int(time.time())}"

        page.locator(Homepage.NEW_SESSION_BUTTON).click(timeout=10000)
        # ... dialog interaction
        return session_name

    return _start


@pytest.fixture
def wb_quit_session(page: Page):
    """Factory fixture to quit a session by name."""

    def _quit(session_name: str):
        checkbox = page.locator(Homepage.session_checkbox(session_name))
        checkbox.click()
        page.locator(Homepage.QUIT_BUTTON).click()
        expect(page.locator(Homepage.session_link(session_name))).not_to_be_visible()

    return _quit
```

### Using Fixtures in Steps

```python
@when("the user starts a new RStudio session")
def start_rstudio_session(page: Page, session_context: dict):
    session_name = f"VIP Test RStudio {int(time.time())}"
    session_context["name"] = session_name
    _start_session(page, "RStudio", session_name)


@then("the session is cleaned up")
def session_cleaned_up(page: Page, workbench_url: str, session_context: dict):
    session_name = session_context["name"]
    # Navigate back to homepage
    page.goto(workbench_url.rstrip("/") + "/home")
    # Quit the session
    checkbox = page.locator(Homepage.session_checkbox(session_name))
    checkbox.click()
    page.locator(Homepage.QUIT_BUTTON).click()
```

---

## Common Pattern Translations

### Login Flow

**rstudio-pro:**
```typescript
await performLogin(page, user.username, user.password);
```

**VIP:**
```python
workbench_login(page, workbench_url, test_username, test_password)
```

The `workbench_login` helper:
- Navigates to `/home` directly (reuses existing sessions)
- Only logs in if redirected to login page
- Checks "Stay signed in" to preserve sessions
- Has retry logic for transient server errors

### Starting a Session

**rstudio-pro:**
```typescript
await homepageActions.startNewSession({
  sessionType: 'RStudio',
  autoJoin: false,
  sessionName
});
await expect(page.getByRole("button", { name: "Starting" })).toBeVisible();
await expect(page.getByRole("button", { name: "Active" })).toBeVisible({ timeout: 60_000 });
```

**VIP:**
```python
page.locator(Homepage.NEW_SESSION_BUTTON).click(timeout=10000)

dialog = page.locator(NewSessionDialog.DIALOG)
expect(dialog.locator(NewSessionDialog.DIALOG_TITLE)).to_have_text("New Session")

# Select IDE type
dialog.get_by_role("tab", name="RStudio Pro").click(timeout=5000)
page.fill(NewSessionDialog.SESSION_NAME, session_name)

# Uncheck auto-join to observe state transitions
checkbox = page.locator(NewSessionDialog.JOIN_CHECKBOX)
if checkbox.is_checked():
    checkbox.click()

page.locator(NewSessionDialog.LAUNCH_BUTTON).click(timeout=5000)

# Wait for session to become active
expect(page.get_by_role("button", name="Active").first).to_be_visible(timeout=90000)
```

### Quitting a Session

**rstudio-pro:**
```typescript
await homepageActions.quitSessionByName(sessionName);
```

**VIP:**
```python
checkbox = page.locator(Homepage.session_checkbox(session_name))
checkbox.click()
page.locator(Homepage.QUIT_BUTTON).click()
expect(page.locator(Homepage.session_link(session_name))).not_to_be_visible(timeout=30000)
```

### Verifying IDE Elements

**rstudio-pro:**
```typescript
await expect(ide.rstudioLogo).toBeVisible({ timeout: 10_000 });
await expect(ide.rstudioContainer).toBeVisible({ timeout: 10_000 });
await expect(ide.projectMenu).toBeVisible({ timeout: 10_000 });
await expect(console.consoleOutput).toBeVisible({ timeout: 10_000 });
```

**VIP:**
```python
expect(page.locator(RStudioSession.LOGO)).to_be_visible(timeout=30000)
expect(page.locator(RStudioSession.CONTAINER)).to_be_visible(timeout=10000)
expect(page.locator(RStudioSession.PROJECT_MENU)).to_be_visible(timeout=10000)
expect(page.locator(ConsolePaneSelectors.OUTPUT)).to_be_visible(timeout=10000)
```

---

## BDD Scenario Writing Guidelines

### Keep Scenarios High-Level

Feature files should be readable by non-developers. Implementation details
belong in step definitions.

**Good:**
```gherkin
Scenario: RStudio IDE session can be launched
  Given the user is logged in to Workbench
  When the user starts a new RStudio session
  Then the session transitions to Active state
  And the RStudio IDE is displayed and functional
  And the session is cleaned up
```

**Too detailed:**
```gherkin
Scenario: RStudio IDE session can be launched
  Given Workbench is accessible at http://localhost:8787
  When I click the New Session button
  And I select the RStudio Pro tab
  And I enter "VIP Test RStudio" as the session name
  And I uncheck the auto-join checkbox
  And I click the Launch button
  Then I see a button labeled "Starting"
  And after 60 seconds I see a button labeled "Active"
```

### Use Product Markers

Every feature file needs a product marker tag at the top:

```gherkin
@workbench
Feature: Workbench authentication
```

This enables auto-skip when the product is not configured.

### Cleanup in Scenarios

Each scenario should clean up resources it creates. Add cleanup as a Then step:

```gherkin
And the session is cleaned up
```

---

## Test Coverage Mapping

### rstudio-pro Test Files and VIP Equivalents

| rstudio-pro Test | Coverage | VIP Equivalent |
|------------------|----------|----------------|
| `login_logout.test.ts` | Login, verify homepage, logout | `test_auth.py` (partial - no logout) |
| `rstudio_session.test.ts` | Session start, IDE verification, console, packages, projects, jobs | `test_ide_launch.py` (partial) |
| `vscode_session.test.ts` | VS Code start, quit, force quit, rename | `test_ide_launch.py` (partial) |
| `positron_session.test.ts` | Positron start, quit, force quit, rename | Not yet implemented |
| `vscode_inactive_session.test.ts` | Inactive session handling | Not yet implemented |
| `positron_inactive_session.test.ts` | Inactive session handling | Not yet implemented |
| `*_session_logs.test.ts` | Session log viewing | Not yet implemented |

### Coverage Gaps to Address

These rstudio-pro test scenarios are not yet covered in VIP:

1. **Session management:**
   - Quit session (basic quit is in cleanup, but not explicit test)
   - Force quit session
   - Rename session
   - Suspend session

2. **IDE functionality:**
   - Console command execution
   - Package installation
   - Project creation and management
   - File operations
   - Workbench jobs

3. **Advanced features:**
   - Session logs viewing
   - Inactive session handling
   - R version selection
   - Resource profile configuration (CPU, memory)
   - Cluster selection

4. **Positron IDE:**
   - Session start/stop
   - IDE verification

---

## Selector Reference

### Login Page

| Element | rstudio-pro | VIP |
|---------|-------------|-----|
| Username | `#username` | `LOGIN_USERNAME = "#username"` |
| Password | `#password` | `LOGIN_PASSWORD = "#password"` |
| Sign in button | `#signinbutton` | `LOGIN_BUTTON = "#signinbutton"` |
| Stay signed in | `#staySignedIn` | `LOGIN_STAY_SIGNED_IN = "#staySignedIn"` |

### Homepage

| Element | rstudio-pro | VIP |
|---------|-------------|-----|
| Posit logo | `#posit-logo` | `POSIT_LOGO = "#posit-logo"` |
| Current user | `#current-user` | `CURRENT_USER = "#current-user"` |
| New Session button | `getByRole('button', { name: 'New Session' })` | `NEW_SESSION_BUTTON = "button:text-is('New Session')"` |
| Quit button | `getByRole('button', { name: 'Quit' })` | `QUIT_BUTTON = "button:text-is('Quit')"` |
| Projects tab | `getByRole('link', { name: 'Projects' })` | `PROJECTS_TAB = "a:text-is('Projects')"` |
| Jobs tab | `getByRole('link', { name: 'Jobs' })` | `JOBS_TAB = "a:text-is('Jobs')"` |
| Session checkbox | `[aria-label='select ${name}']` | `session_checkbox(name)` method |

### New Session Dialog

| Element | rstudio-pro | VIP |
|---------|-------------|-----|
| Dialog | `getByRole('dialog')` | `DIALOG = "[role='dialog']"` |
| Title | `[data-slot='dialog-title']` | `DIALOG_TITLE = "[data-slot='dialog-title']"` |
| Session name | `getByRole('textbox', { name: 'Session Name' })` | `SESSION_NAME_INPUT = "input#rstudio_label_session_name"` |
| IDE tab | `getByRole('tab', { name: 'RStudio Pro' })` | `dialog.get_by_role("tab", name="RStudio Pro")` |
| Auto-join checkbox | `#modal-auto-join-button` | `JOIN_CHECKBOX = "#modal-auto-join-button"` |
| Launch button | `getByRole('button', { name: 'Launch' })` | `LAUNCH_BUTTON = "button:text-is('Launch')"` |

### RStudio IDE

| Element | rstudio-pro | VIP |
|---------|-------------|-----|
| RStudio logo | `#rstudio_rstudio_logo` | `RSTUDIO_LOGO = "#rstudio_rstudio_logo"` |
| Container | `#rstudio_container` | `RSTUDIO_CONTAINER = "#rstudio_container"` |
| Project menu | `#rstudio_project_menubutton_toolbar` | `PROJECT_MENU = "#rstudio_project_menubutton_toolbar"` |
| Console output | `#rstudio_console_output` | `CONSOLE_OUTPUT = "#rstudio_console_output"` |
| Console input | `#rstudio_console_input` | `CONSOLE_INPUT = "#rstudio_console_input"` |

### VS Code IDE

| Element | rstudio-pro | VIP |
|---------|-------------|-----|
| Workbench container | `.monaco-workbench` | `VSCODE_WORKBENCH = ".monaco-workbench"` |
| Status bar | `.statusbar` | `VSCODE_STATUS_BAR = ".statusbar"` |

### JupyterLab IDE

| Element | rstudio-pro | VIP |
|---------|-------------|-----|
| Launcher | `.jp-Launcher` | `JUPYTER_LAUNCHER = ".jp-Launcher"` |
| Notebook panel | `.jp-NotebookPanel` | `JUPYTER_NOTEBOOK = ".jp-NotebookPanel"` |

---

## Timeout Guidelines

| Operation | rstudio-pro | VIP |
|-----------|-------------|-----|
| Element visibility | 10,000ms | 10000 |
| Login form | 15,000ms | 15000 |
| Homepage load | 10,000ms | 15000 |
| Session becoming Active | 60,000ms | 90000 |
| IDE load | 30,000ms | 30000-60000 |
| Session quit confirmation | 30,000ms | 30000 |

VIP uses slightly longer timeouts to accommodate slower test environments.

---

## User Management Difference

### rstudio-pro: Dynamic User Creation

```typescript
const user = await createUser();
await performLogin(page, user.username, user.password);
```

Each test creates a fresh user, providing isolation but requiring PAM/user
management on the test server.

### VIP: Shared Test Credentials

```python
@given("the user is logged in to Workbench")
def user_logged_in(page, workbench_url, test_username, test_password):
    workbench_login(page, workbench_url, test_username, test_password)
```

VIP uses shared credentials from `VIP_TEST_USERNAME` and `VIP_TEST_PASSWORD`
environment variables. This simplifies test setup but means:
- Tests must clean up sessions they create
- Tests should use unique session names (include timestamp)
- Tests may see sessions from prior runs

---

## Currently Skipped Tests: Implementation Guidance

### test_packages.py - R Repository Configuration

**Current state:** Skipped because it scrapes admin pages for URLs, which is
fragile and doesn't reflect actual session configuration.

**rstudio-pro approach for console testing:**
```typescript
// Start session, verify console is ready
await homepageActions.startNewSession({ sessionType: 'RStudio', autoJoin: true });
await ideActions.waitForPageToLoad();

// Execute R command
await consolePaneActions.clearConsoleAndBuffer();
await console.consoleInput.pressSequentially('getOption("repos")');
await console.consoleInput.press('Enter');
await expect(console.consoleOutput).toContainText('https://packagemanager', { timeout: 10_000 });
```

**VIP implementation path:**
1. Start an RStudio session (reuse `_start_session` helper)
2. Wait for IDE to load (verify `RSTUDIO_LOGO`, `CONSOLE_INPUT` visible)
3. Enter command in console: `page.fill(ConsolePaneSelectors.INPUT, 'getOption("repos")')`
4. Press Enter: `page.locator(ConsolePaneSelectors.INPUT).press("Enter")`
5. Verify output contains expected Package Manager URL
6. Clean up session

**New selectors needed:**
```python
# Already defined
CONSOLE_OUTPUT = "#rstudio_console_output"
CONSOLE_INPUT = "#rstudio_console_input"

# May need
CLEAR_CONSOLE_BTN = "[id^='rstudio_tb_consoleclear']"
```

### test_data_sources.py - External Data Source Connectivity

**Current state:** Skipped because it tests connectivity from the test runner
machine, not from inside a Workbench session.

**Implementation path:**
1. Start an RStudio session
2. Wait for console to be ready
3. For each data source, execute a connectivity check in R:
   ```r
   # For HTTP/API data sources
   httr::HEAD("https://datasource.example.com")

   # For database connections (if odbc configured)
   con <- DBI::dbConnect(odbc::odbc(), dsn = "mydsn")
   DBI::dbDisconnect(con)
   ```
4. Check console output for errors
5. Clean up session

**Feature file structure:**
```gherkin
@workbench
Feature: Workbench data source connectivity
  As a Posit Team administrator
  I want to verify that external data sources are reachable from Workbench sessions
  So that users can access their data

  Scenario: HTTP data sources are reachable from an R session
    Given the user is logged in to Workbench
    And an RStudio session is running
    When I test connectivity to each HTTP data source from R
    Then all configured HTTP data sources respond successfully
    And the session is cleaned up
```

---

## Translation Checklist

When translating an rstudio-pro test to VIP:

1. **Create feature file:**
   - Add `@workbench` marker at top
   - Write high-level Gherkin scenarios
   - Include cleanup step in each scenario

2. **Create step definitions:**
   - Import `workbench_login` from conftest and page selectors from `pages/`
   - Link scenarios with `@scenario()` decorators
   - Use shared fixtures for login (`wb_login`) and session management

3. **Translate selectors:**
   - Add any new selectors to the appropriate `pages/` module
   - Use `:text-is()` for exact text matching
   - Use static methods for dynamic selectors

4. **Translate assertions:**
   - Convert `toBeVisible()` to `to_be_visible()`
   - Convert `toHaveText()` to `to_have_text()`
   - Convert `not.toBeVisible()` to `not_to_be_visible()`
   - Use keyword arguments for timeout

5. **Add cleanup:**
   - Navigate back to `/home` after IDE verification
   - Quit sessions using checkbox + Quit button
   - Verify session disappears from list

6. **Test locally:**
   ```bash
   source .env
   uv run pytest tests/workbench/<new_test>.py -v --headed
   ```

7. **Run lint/format:**
   ```bash
   just check
   ```
