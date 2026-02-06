@performance
Feature: Concurrent workload stability
  As a Posit Team administrator
  I want to verify system stability under concurrent usage
  So that the deployment can handle multiple simultaneous users

  Scenario: Multiple concurrent API requests to Connect succeed
    Given Connect is configured in vip.toml
    When I send 10 concurrent health-check requests to Connect
    Then all requests succeed
    And the average response time is under 5 seconds

  Scenario: Multiple concurrent requests to Package Manager succeed
    Given Package Manager is configured in vip.toml
    When I send 10 concurrent status requests to Package Manager
    Then all requests succeed
    And the average response time is under 5 seconds
