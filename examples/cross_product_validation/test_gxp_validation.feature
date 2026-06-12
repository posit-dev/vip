Feature: Cross-product runtime and package validation
  As a Posit Team administrator in a regulated environment
  I want to verify that specific R and Python versions are available
  And that key packages are installable across Workbench and Connect
  So that GxP and other compliance requirements are continuously met

  @connect
  Scenario: Connect R versions match requirements
    Given Connect is accessible at the configured URL
    And expected R versions are specified in vip.toml
    When I query Connect for available R versions
    Then all expected R versions are present on Connect

  @connect
  Scenario: Connect Python versions match requirements
    Given Connect is accessible at the configured URL
    And expected Python versions are specified in vip.toml
    When I query Connect for available Python versions
    Then all expected Python versions are present on Connect

  @connect
  Scenario: R package is installable on Connect
    Given Connect is accessible at the configured URL
    And package install checks are enabled
    When I deploy a minimal content item that installs the R package
    Then the deployment succeeds
    And I clean up the deployed content

  @connect
  Scenario: Python package is installable on Connect
    Given Connect is accessible at the configured URL
    And package install checks are enabled
    When I deploy a minimal content item that installs the Python package
    Then the deployment succeeds
    And I clean up the deployed content

  @workbench
  Scenario: R package is installable in Workbench RStudio session
    Given a Workbench RStudio session is open
    And package install checks are enabled
    When I install the R package in the terminal
    Then the installation succeeds
