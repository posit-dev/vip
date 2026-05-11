@workbench
Feature: Workbench IDE extensions
  As a Posit Team administrator
  I want to verify that required extensions are installed in each IDE
  So that users have the tools they need when they start a session

  The Posit Workbench integration extension is always checked.
  Administrators can declare additional required extensions per IDE
  in vip.toml under [workbench.extensions].

  Scenario: VS Code has required extensions
    Given the user is logged in to Workbench
    When the user starts a new VS Code session
    Then the session transitions to Active state
    And the VS Code IDE is displayed
    And the Posit Workbench extension is visible in VS Code
    And all configured VS Code extensions are installed
    And the session is cleaned up

  Scenario: JupyterLab has required extensions
    Given the user is logged in to Workbench
    When the user starts a new JupyterLab session
    Then the session transitions to Active state
    And the JupyterLab IDE is displayed
    And the Posit Workbench extension is visible in JupyterLab
    And all configured JupyterLab extensions are installed
    And the session is cleaned up

  Scenario: Positron has required extensions
    Given the user is logged in to Workbench
    When the user starts a new Positron session
    Then the session transitions to Active state
    And the Positron IDE is displayed
    And the Posit Workbench extension is visible in Positron
    And all configured Positron extensions are installed
    And the session is cleaned up
