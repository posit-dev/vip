@prerequisites
Feature: Product versions match configuration
  As a Posit Team administrator
  I want to verify that the running product versions match the configured expectations
  So that I know the correct software versions are deployed

  Scenario: Connect version matches configuration
    Given Connect is configured in vip.toml with a version expectation
    When I fetch the Connect server version
    Then the Connect version matches the configured value

  # Workbench version is verified separately in the @workbench browser suite
  # (workbench/test_version.feature): Workbench exposes no unauthenticated
  # version endpoint, so the running version is read from the authenticated
  # homepage footer rather than an API call.

  Scenario: Package Manager version matches configuration
    Given Package Manager is configured in vip.toml with a version expectation
    When I fetch the Package Manager server version
    Then the Package Manager version matches the configured value
