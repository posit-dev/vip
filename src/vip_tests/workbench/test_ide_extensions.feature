@workbench
Feature: Workbench IDE extensions
  As a Posit Team administrator
  I want to verify that the Posit Workbench extension is installed in each IDE
  So that users have seamless integration between their IDE and Workbench

  Scenario: VS Code has the Posit Workbench extension
    Given the user is logged in to Workbench
    When the user starts a new VS Code session
    Then the session transitions to Active state
    And the VS Code IDE is displayed
    And the Posit Workbench extension is visible in VS Code
    And the session is cleaned up

  Scenario: JupyterLab has the Posit Workbench extension
    Given the user is logged in to Workbench
    When the user starts a new JupyterLab session
    Then the session transitions to Active state
    And the JupyterLab IDE is displayed
    And the Posit Workbench extension is visible in JupyterLab
    And the session is cleaned up

  Scenario: Positron has the Posit Workbench extension
    Given the user is logged in to Workbench
    When the user starts a new Positron session
    Then the session transitions to Active state
    And the Positron IDE is displayed
    And the Posit Workbench extension is visible in Positron
    And the session is cleaned up
