@performance
Feature: Login and page load times
  As a Posit Team administrator
  I want to verify that login and page load times are acceptable
  So that users have a responsive experience

  Scenario: Connect login page loads within acceptable time
    Given Connect is configured in vip.toml
    When I measure the Connect login page load time
    Then the page loads in under 10 seconds

  Scenario: Workbench login page loads within acceptable time
    Given Workbench is configured in vip.toml
    When I measure the Workbench login page load time
    Then the page loads in under 10 seconds

  Scenario: Package Manager home page loads within acceptable time
    Given Package Manager is configured in vip.toml
    When I measure the Package Manager home page load time
    Then the page loads in under 10 seconds
