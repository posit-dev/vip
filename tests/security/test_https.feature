@security
Feature: HTTPS enforcement
  As a Posit Team administrator
  I want to verify that HTTPS is enforced across all products
  So that traffic is encrypted in transit

  Scenario Outline: <product> enforces HTTPS
    Given <product> is configured with an HTTPS URL
    When I make an HTTP request to <product>
    Then the connection is refused or redirected to HTTPS

  Examples:
    | product         |
    | Connect         |
    | Workbench       |
    | Package Manager |

  Scenario Outline: <product> does not expose sensitive headers
    Given <product> is configured in vip.toml
    When I inspect response headers from <product>
    Then the server does not expose version information in headers

  Examples:
    | product         |
    | Connect         |
    | Workbench       |
    | Package Manager |
