@performance
Feature: Realistic session simulation
  As a Posit Team administrator
  I want to simulate realistic concurrent sessions against each product
  So that I can validate the deployment handles real-world traffic patterns

  @requires_connect
  Scenario Outline: Connect handles <users> concurrent sessions
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

  @requires_workbench
  Scenario Outline: Workbench handles <users> concurrent sessions
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

  @requires_package_manager
  Scenario Outline: Package Manager handles <users> concurrent sessions
    Given Package Manager is configured in vip.toml
    When I simulate <users> concurrent users on Package Manager
    Then the simulation success rate is at least the configured threshold
    And the simulation p95 response time is within the configured threshold

    Examples:
      | users |
      | 10    |
      | 100   |
