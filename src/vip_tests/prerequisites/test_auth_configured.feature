@prerequisites
Feature: Authentication is configured
  As a Posit Team administrator
  I want to verify that authentication credentials are available
  So that login-dependent tests can proceed

  Scenario: Test credentials are provided
    Given VIP is configured with test user credentials
    Then the username is not empty
    And the password is not empty
