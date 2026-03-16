@prerequisites
Feature: Product versions match configuration
  As a Posit Team administrator
  I want to verify that the running product versions match the configured expectations
  So that I know the correct software versions are deployed

  Scenario: Connect version matches configuration
    Given Connect is configured in vip.toml with a version expectation
    When I fetch the Connect server version
    Then the Connect version matches the configured value

  Scenario: Workbench version matches configuration
    Given Workbench is configured in vip.toml with a version expectation
    When I fetch the Workbench server version
    Then the Workbench version matches the configured value

  Scenario: Package Manager version matches configuration
    Given Package Manager is configured in vip.toml with a version expectation
    When I fetch the Package Manager server version
    Then the Package Manager version matches the configured value
