@package_manager
Feature: Part 11 flavoured controls for Package Manager
  As a validation lead in a regulated environment
  I want evidence that analyses draw on a controlled, reconstructable package set
  So that a record can be traced back to the software that produced it

  @control-package-source-controlled
  Scenario: The deployment serves a defined set of repositories
    Given Package Manager is accessible at the configured URL
    When I list the configured repositories
    Then at least one repository is served, and each one is named

  @control-package-environment-reproducible
  Scenario: A past package set can still be retrieved
    Given Package Manager is accessible at the configured URL
    When I request the package index for the validated snapshot
    Then the snapshot's index is served
