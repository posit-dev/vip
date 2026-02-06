@performance
Feature: System resource usage during workloads
  As a Posit Team administrator
  I want to verify that resource usage stays within limits during typical use
  So that the system has adequate capacity

  Scenario: CPU and memory stay within limits during API activity
    Given at least one product is configured
    When I generate moderate API traffic for 10 seconds
    Then system load average is below the CPU count
    And available memory stays above 10 percent
