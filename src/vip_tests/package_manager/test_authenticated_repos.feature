@package_manager @if_applicable
Feature: Authenticated package repositories
  As a Posit Team administrator
  I want to verify that authenticated Package Manager repositories enforce tokens
  So that protected content is only served to authorized clients

  Scenario: At least one authenticated repository is configured
    Given Package Manager is running
    And a Package Manager token is configured
    When I list authenticated repositories
    Then at least one authenticated repository exists

  Scenario: Authenticated repository denies access without a token
    Given Package Manager is running
    And a Package Manager token is configured
    And an authenticated repository is configured
    When I query the authenticated repository without a token
    Then access is denied

  Scenario: Authenticated repository allows access with a token
    Given Package Manager is running
    And a Package Manager token is configured
    And an authenticated repository is configured
    When I query the authenticated repository with the configured token
    Then the repository responds successfully
