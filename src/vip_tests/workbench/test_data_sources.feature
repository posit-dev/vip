@workbench @if_applicable
Feature: Workbench external data sources
  As a Posit Team administrator
  I want to verify that external data sources are accessible from Workbench
  So that users can connect to databases and services from their sessions

  Scenario: External data sources are reachable from Workbench
    Given Workbench is accessible at the configured URL
    And external data sources are configured in vip.toml
    When I verify data source connectivity
    Then all data sources are reachable
