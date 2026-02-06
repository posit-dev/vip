@security
Feature: HTTPS enforcement
  As a Posit Team administrator
  I want to verify that HTTPS is enforced across all products
  So that traffic is encrypted in transit

  Scenario: Connect enforces HTTPS
    Given Connect is configured with an HTTPS URL
    When I make an HTTP request to Connect
    Then the connection is refused or redirected to HTTPS

  Scenario: Workbench enforces HTTPS
    Given Workbench is configured with an HTTPS URL
    When I make an HTTP request to Workbench
    Then the connection is refused or redirected to HTTPS

  Scenario: Package Manager enforces HTTPS
    Given Package Manager is configured with an HTTPS URL
    When I make an HTTP request to Package Manager
    Then the connection is refused or redirected to HTTPS

  Scenario: Connect does not expose sensitive headers
    Given Connect is configured in vip.toml
    When I inspect response headers from Connect
    Then the server does not expose version information in headers

  Scenario: Workbench does not expose sensitive headers
    Given Workbench is configured in vip.toml
    When I inspect response headers from Workbench
    Then the server does not expose version information in headers

  Scenario: Package Manager does not expose sensitive headers
    Given Package Manager is configured in vip.toml
    When I inspect response headers from Package Manager
    Then the server does not expose version information in headers
