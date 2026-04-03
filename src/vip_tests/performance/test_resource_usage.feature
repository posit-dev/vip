@performance
Feature: Remote product performance under load
  As a Posit Team administrator
  I want to verify that products respond quickly under moderate load
  So that users experience acceptable performance

  Scenario: Products respond within acceptable time under moderate load
    Given at least one product is configured
    When I generate moderate API traffic for 10 seconds
    Then the p95 response time is within the configured threshold
    And the error rate is below 10 percent

  Scenario: Prometheus metrics endpoint is enabled
    Given at least one product is configured
    Then each product has a working Prometheus metrics endpoint
