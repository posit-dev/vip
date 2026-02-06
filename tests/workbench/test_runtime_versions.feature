@workbench
Feature: Workbench R and Python versions
  As a Posit Team administrator
  I want to verify that the expected R and Python versions are available
  So that users can work with the correct runtime

  Scenario: Expected R versions are available on Workbench
    Given the user is logged in to Workbench
    And expected R versions are specified in vip.toml
    When I check available R versions on Workbench
    Then all expected R versions are found

  Scenario: Expected Python versions are available on Workbench
    Given the user is logged in to Workbench
    And expected Python versions are specified in vip.toml
    When I check available Python versions on Workbench
    Then all expected Python versions are found
