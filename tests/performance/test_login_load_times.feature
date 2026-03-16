@performance
Feature: Login and page load times
  As a Posit Team administrator
  I want to verify that login and page load times are acceptable
  So that users have a responsive experience

  Scenario Outline: <product> login page loads within acceptable time
    Given <product> is configured in vip.toml
    When I measure the <product> login page load time
    Then the page loads in under 10 seconds

    Examples:
      | product         |
      | Connect         |
      | Workbench       |
      | Package Manager |
