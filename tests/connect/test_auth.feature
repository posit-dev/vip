@connect
Feature: Connect authentication
  As a Posit Team administrator
  I want to verify that users can log in to Connect
  So that I know authentication is properly configured

  Scenario: User can log in via the web UI
    Given Connect is accessible at the configured URL
    When a user navigates to the Connect login page
    And enters valid credentials
    Then the user is successfully authenticated
    And the Connect dashboard is displayed

  Scenario: API key authentication works
    Given Connect is accessible at the configured URL
    And a valid API key is configured
    When I request the current user via the API
    Then the API returns user information
