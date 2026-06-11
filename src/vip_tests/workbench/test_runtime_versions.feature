@workbench
Feature: Workbench R and Python versions
  As a Posit Team administrator
  I want to verify that the expected R and Python versions are available
  So that users can start sessions with the correct runtime

  Scenario: Expected R versions are available in Workbench session dialog
    Given the user is logged in to Workbench
    And expected R versions are specified in vip.toml
    When I check the available R versions in the New Session dialog
    Then all expected R versions are present in the R version selector
    And no excluded R versions are present in the R version selector

  Scenario: Expected Python versions are available in Workbench session dialog
    Given the user is logged in to Workbench
    And expected Python versions are specified in vip.toml
    When I check the available Python versions in the New Session dialog
    Then all expected Python versions are present in the Python version selector
    And no excluded Python versions are present in the Python version selector

  Scenario: Launched RStudio session uses expected R version
    Given the user is logged in to Workbench
    And expected R versions are specified in vip.toml
    When the user starts a new RStudio session with the first expected R version
    Then the session transitions to Active state
    And the RStudio console reports the expected R version
    And the session is cleaned up
