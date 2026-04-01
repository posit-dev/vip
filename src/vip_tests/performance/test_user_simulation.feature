@performance
Feature: Realistic user simulation
  As a Posit Team administrator
  I want to simulate realistic concurrent user sessions against each product
  So that I can validate the deployment handles real-world usage patterns

  Scenario Outline: Connect supports <users> concurrent users
    Given Connect is configured in vip.toml
    When I simulate <users> concurrent users on Connect
    Then the simulation success rate is at least the configured threshold
    And the simulation p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 100   |
      | 1000  |
      | 10000 |

  Scenario Outline: Workbench supports <users> concurrent users
    Given Workbench is configured in vip.toml
    When I simulate <users> concurrent users on Workbench
    Then the simulation success rate is at least the configured threshold
    And the simulation p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 100   |
      | 1000  |
      | 10000 |

  Scenario Outline: Package Manager supports <users> concurrent users
    Given Package Manager is configured in vip.toml
    When I simulate <users> concurrent users on Package Manager
    Then the simulation success rate is at least the configured threshold
    And the simulation p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 100   |
      | 1000  |
      | 10000 |
