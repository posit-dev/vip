@workbench @connect @slow
Feature: Publish from Workbench to Connect
  As a Posit Team administrator
  I want to verify that a user can deploy content from a Workbench session to Connect
  So that the user-facing publish workflow is validated end-to-end

  Scenario: User deploys a Python Shiny app from a Workbench terminal
    Given the user is logged in to Workbench
    And the user opens a VS Code session
    When the user deploys the Python Shiny app via the terminal
    Then the app is reachable on Connect

  Scenario: User deploys via Posit Publisher extension
    Given the user is logged in to Workbench
    And the user opens a VS Code session
    When the user deploys via the Posit Publisher extension UI
    Then the app is reachable on Connect
