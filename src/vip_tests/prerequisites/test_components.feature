@prerequisites
Feature: Posit Team components are installed and reachable
  As a Posit Team administrator
  I want to verify that all configured components are running
  So that I know the basic installation is healthy before running deeper tests

  Scenario Outline: <product> server is reachable
    Given <product> is configured in vip.toml
    When I request the <product> health endpoint
    Then the server responds with a successful status code

    Examples:
      | product         |
      | Connect         |
      | Workbench       |
      | Package Manager |
