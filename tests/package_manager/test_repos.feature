@package_manager
Feature: Package Manager repositories
  As a Posit Team administrator
  I want to verify that CRAN and PyPI mirrors are working
  So that R and Python packages can be installed from the correct source

  Scenario: CRAN mirror is accessible
    Given Package Manager is running
    When I query the CRAN repository for the "Matrix" package
    Then the package is found in the repository

  Scenario: PyPI mirror is accessible
    Given Package Manager is running
    When I query the PyPI repository for the "requests" package
    Then the package is found in the repository

  Scenario: At least one repository is configured
    Given Package Manager is running
    When I list all repositories
    Then at least one repository exists
