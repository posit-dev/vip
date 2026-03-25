@security
Feature: Authentication policy alignment
  As a Posit Team administrator
  I want to verify that authentication aligns with organizational policy
  So that access controls meet compliance requirements

  Scenario: Auth provider matches expected configuration
    Given the expected auth provider is specified in vip.toml
    When I check the auth configuration
    Then the configured provider matches expectations

  Scenario: Unauthenticated API access is denied
    Given Connect is configured in vip.toml
    When I make an unauthenticated API request to Connect
    Then the request is rejected with 401 or 403
