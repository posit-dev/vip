@cross_product
Feature: SSL certificates and HTTPS
  As a Posit Team administrator
  I want to verify that SSL certificates are valid and HTTPS is enforced
  So that all traffic is encrypted

  Scenario Outline: SSL certificate is valid for <product>
    Given <product> is configured in vip.toml
    When I check the SSL certificate for <product>
    Then the certificate is valid and not expired
    And the certificate chain is complete

  Examples:
    | product         |
    | Connect         |
    | Workbench       |
    | Package Manager |

  Scenario Outline: HTTP redirects to HTTPS for <product>
    Given <product> is configured in vip.toml
    When I request the HTTP URL for <product>
    Then the response redirects to HTTPS
      Or the HTTP port is not open

  Examples:
    | product         |
    | Connect         |
    | Workbench       |
    | Package Manager |
