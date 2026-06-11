@workbench
Feature: Workbench authentication
  As a Posit Team administrator
  I want to verify that users can log in to Workbench
  So that I know authentication is properly configured

  Scenario: User can log in to Workbench via the web UI
    Given Workbench is accessible at the configured URL
    When a user navigates to the Workbench login page and enters valid credentials
    Then the Workbench homepage is displayed
    And the current user is shown in the header

  Scenario: User can sign out of Workbench
    Given Workbench is accessible and I am logged in
    When I sign out of Workbench
    Then I am redirected to the Workbench login page
