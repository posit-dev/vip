@workbench @api_auth
Feature: Workbench IDE launch via the Admin API
  As a Posit Team administrator whose Workbench is behind non-scriptable SSO
  I want to verify each IDE launches using only a Workbench API token
  So that I can confirm session-launch works without a browser login

  Scenario: RStudio session launches via the API and becomes active
    Given a Workbench API token that can launch sessions
    When I launch the "RStudio" IDE for the test user via the API
    Then the session reaches the active state
    And the session is stopped via the API

  Scenario: VS Code session launches via the API and becomes active
    Given a Workbench API token that can launch sessions
    When I launch the "VS Code" IDE for the test user via the API
    Then the session reaches the active state
    And the session is stopped via the API

  Scenario: JupyterLab session launches via the API and becomes active
    Given a Workbench API token that can launch sessions
    When I launch the "JupyterLab" IDE for the test user via the API
    Then the session reaches the active state
    And the session is stopped via the API

  Scenario: Positron session launches via the API and becomes active
    Given a Workbench API token that can launch sessions
    When I launch the "Positron" IDE for the test user via the API
    Then the session reaches the active state
    And the session is stopped via the API
