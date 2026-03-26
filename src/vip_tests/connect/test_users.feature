@connect
Feature: Connect user management
  As a Posit Team administrator
  I want to verify that user and group management APIs are functional
  So that I know access control is properly configured

  Scenario: Admin user exists and has admin privileges
    Given Connect is accessible at the configured URL
    When I retrieve the current user profile
    Then the user has admin privileges

  Scenario: Users can be listed
    Given Connect is accessible at the configured URL
    When I list all users
    Then the user list is not empty
    And the test user exists in the user list

  Scenario: Groups can be listed
    Given Connect is accessible at the configured URL
    When I list all groups
    Then the response is successful
