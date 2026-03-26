@cross_product
Feature: Product server health
  As a Posit Team administrator
  I want to verify that all configured product servers respond to health checks
  So that I know the services are running and reachable

  Scenario: All configured products respond to health checks
    Given at least one product is configured
    When I check the health of each configured product
    Then all products respond with a healthy status
