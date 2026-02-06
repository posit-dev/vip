@performance @package_manager
Feature: Package installation speed
  As a Posit Team administrator
  I want to verify that package downloads from Package Manager are fast
  So that users and deployments are not blocked by slow installs

  Scenario: CRAN package downloads within acceptable time
    Given Package Manager is running and has a CRAN repo
    When I download a small CRAN package
    Then the download completes in under 30 seconds

  Scenario: PyPI package downloads within acceptable time
    Given Package Manager is running and has a PyPI repo
    When I download a small PyPI package
    Then the download completes in under 30 seconds
