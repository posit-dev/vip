@package_manager @if_applicable
Feature: Private package repositories
  As a Posit Team administrator
  I want to verify that private package repos resolve correctly
  So that internal packages can be installed

  Scenario: Private repositories are reachable
    Given Package Manager is running
    And private repositories are configured
    When I query each private repository
    Then each repository responds successfully
