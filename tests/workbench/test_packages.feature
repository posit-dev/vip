@workbench
Feature: Workbench package installation source
  As a Posit Team administrator
  I want to verify that Workbench installs packages from the correct source
  So that package provenance matches organizational policy

  Scenario: R repos.conf points to the expected repository
    Given the user is logged in to Workbench
    When I check the configured R repositories in the session
    Then the expected package repository URL is present
