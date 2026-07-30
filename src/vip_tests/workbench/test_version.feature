@workbench
Feature: Workbench version matches configuration
  As a Posit Team administrator
  I want to verify that the running Workbench version matches the configured expectation
  So that I know the correct Workbench release is deployed

  # Workbench exposes no unauthenticated version endpoint (the REST API's
  # /api/version is tier-gated, disabled by default, and needs an API token),
  # so the running version is read from the authenticated homepage footer.

  Scenario: Workbench version matches configuration
    Given Workbench is accessible and I am logged in
    And Workbench has a version expectation in vip.toml
    When I read the Workbench version from the homepage footer
    Then the Workbench version matches the configured value
