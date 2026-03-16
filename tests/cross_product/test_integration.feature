@cross_product
Feature: Cross-product integration
  As a Posit Team administrator
  I want to verify that products are integrated with each other
  So that the deployment functions as a cohesive platform

  Scenario: Content deployed on Connect uses packages from Package Manager
    Given Connect is configured in vip.toml
    And Package Manager is configured in vip.toml
    When I deploy a content item that installs R packages on Connect
    Then the deployment logs mention the Package Manager URL as the package source
    And I clean up the integration test content
