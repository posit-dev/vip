@connect
Feature: Connect system checks
  As a Posit Team administrator
  I want to run the Connect system diagnostics
  So that I can verify the Connect installation is healthy

  Scenario: Connect system checks can be run and the report downloaded
    Given Connect is accessible at the configured URL
    And a valid API key is configured
    When I trigger a new system check run via the Connect API
    Then the system check report is returned
    And I can download the system check report artifact
