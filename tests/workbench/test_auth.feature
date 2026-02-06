@workbench
Feature: Workbench authentication
  As a Posit Team administrator
  I want to verify that users can log in to Workbench
  So that I know authentication is properly configured

  Scenario: User can log in to Workbench via the web UI
    Given Workbench is accessible at the configured URL
    When a user navigates to the Workbench login page
    And enters valid Workbench credentials
    Then the user is redirected to the Workbench home page
