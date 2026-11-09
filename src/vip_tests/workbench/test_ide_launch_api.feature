@workbench @api_auth
Feature: Workbench IDE launch via the Workbench API
  As a Posit Team administrator whose Workbench sign-in cannot be scripted
  I want to verify that each IDE launches using only a Workbench API token
  So that I can confirm sessions start without a browser login

  Scenario: RStudio session can be launched through the API
    Given a Workbench API token that can launch sessions
    When I launch the "RStudio" IDE for the test user through the API
    Then the session reaches the running state
    And the session can be stopped through the API

  Scenario: VS Code session can be launched through the API
    Given a Workbench API token that can launch sessions
    When I launch the "VS Code" IDE for the test user through the API
    Then the session reaches the running state
    And the session can be stopped through the API

  Scenario: JupyterLab session can be launched through the API
    Given a Workbench API token that can launch sessions
    When I launch the "JupyterLab" IDE for the test user through the API
    Then the session reaches the running state
    And the session can be stopped through the API

  Scenario: Positron session can be launched through the API
    Given a Workbench API token that can launch sessions
    When I launch the "Positron" IDE for the test user through the API
    Then the session reaches the running state
    And the session can be stopped through the API
