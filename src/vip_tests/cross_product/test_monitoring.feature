@cross_product @if_applicable
Feature: Monitoring and logging
  As a Posit Team administrator
  I want to verify that monitoring and logging are configured
  So that operational issues can be detected and diagnosed

  Scenario: Monitoring is configured
    Given monitoring is enabled in vip.toml
    When I check product health endpoints
    Then all configured products respond to health checks
