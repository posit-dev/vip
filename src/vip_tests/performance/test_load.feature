@performance
Feature: Concurrent user load testing
  As a Posit Team administrator
  I want to verify that each product handles multiple concurrent authenticated users
  So that the deployment performs acceptably under realistic user load

  Scenario: Connect handles concurrent authenticated user requests
    Given Connect is configured in vip.toml
    When I run a load test with concurrent users against Connect
    Then the load test success rate is at least 95 percent
    And the load test p95 response time is within the configured threshold

  Scenario: Workbench handles concurrent user requests
    Given Workbench is configured in vip.toml
    When I run a load test with concurrent users against Workbench
    Then the load test success rate is at least 95 percent
    And the load test p95 response time is within the configured threshold

  Scenario: Package Manager handles concurrent user requests
    Given Package Manager is configured in vip.toml
    When I run a load test with concurrent users against Package Manager
    Then the load test success rate is at least 95 percent
    And the load test p95 response time is within the configured threshold
