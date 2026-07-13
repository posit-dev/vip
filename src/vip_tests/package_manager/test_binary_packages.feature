@package_manager
Feature: Package Manager binary package serving
  As an R or Python user
  I want to install pre-compiled binary packages from Package Manager
  So that packages install faster without local compilation

  Scenario: CRAN Windows binaries are served
    Given Package Manager is running
    When I request the CRAN Windows binary package index
    Then the binary package index is reachable

  Scenario: CRAN macOS binaries are served
    Given Package Manager is running
    When I request the CRAN macOS binary package index
    Then the binary package index is reachable

  Scenario: CRAN Linux binaries are served
    Given Package Manager is running
    When I request the CRAN Linux binary package index
    Then the binary package index is reachable

  Scenario: PyPI wheel packages are available
    Given Package Manager is running
    When I check the PyPI repository for wheel files for the "numpy" package
    Then the binary package index is reachable
