@cross_product
Feature: SSL certificates and HTTPS
  As a Posit Team administrator
  I want to verify that SSL certificates are valid and HTTPS is enforced
  So that all traffic is encrypted

  Scenario: SSL certificate is valid for Connect
    Given Connect is configured in vip.toml
    When I check the SSL certificate for Connect
    Then the certificate is valid and not expired
    And the certificate chain is complete

  Scenario: SSL certificate is valid for Workbench
    Given Workbench is configured in vip.toml
    When I check the SSL certificate for Workbench
    Then the certificate is valid and not expired
    And the certificate chain is complete

  Scenario: SSL certificate is valid for Package Manager
    Given Package Manager is configured in vip.toml
    When I check the SSL certificate for Package Manager
    Then the certificate is valid and not expired
    And the certificate chain is complete

  Scenario: HTTP redirects to HTTPS for Connect
    Given Connect is configured in vip.toml
    When I request the HTTP URL for Connect
    Then the response redirects to HTTPS
    And the HTTP port is not open

  Scenario: HTTP redirects to HTTPS for Workbench
    Given Workbench is configured in vip.toml
    When I request the HTTP URL for Workbench
    Then the response redirects to HTTPS
    And the HTTP port is not open

  Scenario: HTTP redirects to HTTPS for Package Manager
    Given Package Manager is configured in vip.toml
    When I request the HTTP URL for Package Manager
    Then the response redirects to HTTPS
    And the HTTP port is not open
