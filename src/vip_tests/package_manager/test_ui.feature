@package_manager
Feature: Package Manager web UI
  As a Posit Team administrator
  I want to verify that the Package Manager web UI renders and package search works
  So that end users can browse and find packages after a deployment

  Background:
    Given the Package Manager web UI is reachable

  Scenario: Homepage renders its core surfaces
    When I open the Package Manager homepage
    Then the homepage hero, repository selector, and package search bar are visible

  Scenario Outline: Package search returns a result for <ecosystem>
    Given a "<ecosystem>" repository with a known package is available
    When I search for that package in the web UI
    Then the package appears in the search results

    Examples:
      | ecosystem    |
      | CRAN         |
      | PyPI         |
      | Bioconductor |
      | OpenVSX      |

  Scenario Outline: Package detail page renders for <ecosystem>
    Given a "<ecosystem>" repository with a known package is available
    When I open that package's detail page in the web UI
    Then the package detail page shows the package metadata

    Examples:
      | ecosystem    |
      | CRAN         |
      | PyPI         |
      | Bioconductor |
      | OpenVSX      |
