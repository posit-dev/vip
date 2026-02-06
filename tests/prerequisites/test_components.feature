@prerequisites
Feature: Posit Team components are installed and reachable
  As a Posit Team administrator
  I want to verify that all configured components are running
  So that I know the basic installation is healthy before running deeper tests

  Scenario: Connect server is reachable
    Given Connect is configured in vip.toml
    When I request the Connect health endpoint
    Then the server responds with a successful status code

  Scenario: Workbench server is reachable
    Given Workbench is configured in vip.toml
    When I request the Workbench health endpoint
    Then the server responds with a successful status code

  Scenario: Package Manager server is reachable
    Given Package Manager is configured in vip.toml
    When I request the Package Manager status endpoint
    Then the server responds with a successful status code
