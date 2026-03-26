@performance
Feature: Concurrent user load testing
  As a Posit Team administrator
  I want to verify that each product handles multiple concurrent authenticated users
  So that the deployment performs acceptably under realistic user load

  Scenario Outline: Connect handles <users> concurrent authenticated users
    Given Connect is configured in vip.toml
    When I run a load test with <users> concurrent users against Connect
    Then the load test success rate is at least 95 percent
    And the load test p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 20    |
      | 50    |
      | 100   |

  Scenario Outline: Workbench handles <users> concurrent users
    Given Workbench is configured in vip.toml
    When I run a load test with <users> concurrent users against Workbench
    Then the load test success rate is at least 95 percent
    And the load test p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 20    |
      | 50    |
      | 100   |

  Scenario Outline: Package Manager handles <users> concurrent users
    Given Package Manager is configured in vip.toml
    When I run a load test with <users> concurrent users against Package Manager
    Then the load test success rate is at least 95 percent
    And the load test p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 20    |
      | 50    |
      | 100   |
