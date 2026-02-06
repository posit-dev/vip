@cross_product
Feature: System resource usage
  As a Posit Team administrator
  I want to verify that system resource usage is within acceptable limits
  So that the deployment has headroom for normal operations

  Scenario: System resource usage is within limits
    Given at least one product is configured
    When I check system resource usage
    Then disk usage is below 90 percent
    And the system is not under memory pressure
