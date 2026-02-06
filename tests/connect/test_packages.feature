@connect
Feature: Connect package installation source
  As a Posit Team administrator
  I want to verify that Connect installs packages from the correct source
  So that package provenance is as expected (PPPM, PPM, CRAN, etc.)

  Scenario: Connect is configured to use the expected package repository
    Given Connect is accessible at the configured URL
    When I query the Connect server settings for package repositories
    Then the configured R repository URL is present in the settings

  Scenario: Package Manager URL is the default repository source
    Given Connect is accessible at the configured URL
    And Package Manager is configured in vip.toml
    When I query the Connect server settings for package repositories
    Then the Package Manager URL appears as a configured repository
