@workbench
Feature: Workbench IDE launch
  As a Posit Team administrator
  I want to verify that all configured IDEs launch properly
  So that users can start working in their preferred environment

  Scenario: RStudio IDE session can be launched
    Given the user is logged in to Workbench
    When the user starts a new RStudio session
    Then the session transitions to Active state
    And the RStudio IDE is displayed and functional
    And the session is cleaned up

  Scenario: VS Code session can be launched
    Given the user is logged in to Workbench
    When the user starts a new VS Code session
    Then the session transitions to Active state
    And the VS Code IDE is displayed
    And the session is cleaned up

  Scenario: JupyterLab session can be launched
    Given the user is logged in to Workbench
    When the user starts a new JupyterLab session
    Then the session transitions to Active state
    And the JupyterLab IDE is displayed
    And the session is cleaned up

  Scenario: Positron session can be launched
    Given the user is logged in to Workbench
    When the user starts a new Positron session
    Then the session transitions to Active state
    And the Positron IDE is displayed
    And the session is cleaned up
