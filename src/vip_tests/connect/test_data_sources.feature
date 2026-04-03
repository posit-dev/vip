@connect @if_applicable
Feature: Connect external data sources
  As a Posit Team administrator
  I want to verify that external data sources connect and function
  So that published content can access the databases and services it needs

  Scenario: External data sources are reachable from Connect
    Given Connect is accessible at the configured URL
    And external data sources are configured in vip.toml
    When I test connectivity to each data source
    Then all data sources respond successfully
