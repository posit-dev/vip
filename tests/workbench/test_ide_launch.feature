@workbench
Feature: Workbench IDE launch
  As a Posit Team administrator
  I want to verify that all configured IDEs launch properly
  So that users can start working in their preferred environment

  Scenario: RStudio IDE session can be launched
    Given the user is logged in to Workbench
    When the user launches an RStudio session
    Then the session starts within a reasonable time
    And the RStudio IDE is displayed

  Scenario: VS Code session can be launched
    Given the user is logged in to Workbench
    When the user launches a VS Code session
    Then the session starts within a reasonable time
    And the VS Code IDE is displayed

  Scenario: JupyterLab session can be launched
    Given the user is logged in to Workbench
    When the user launches a JupyterLab session
    Then the session starts within a reasonable time
    And the JupyterLab IDE is displayed
