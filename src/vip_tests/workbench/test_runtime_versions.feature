@workbench
Feature: Workbench R and Python versions
  As a Posit Team administrator
  I want to verify that the expected R and Python versions are available
  So that users can start sessions with the correct runtime

  Scenario: Launched RStudio session uses expected R version
    Given the user is logged in to Workbench
    And expected R versions are specified in vip.toml
    When the user starts a new RStudio session with the first expected R version
    Then the session transitions to Active state
    And the RStudio console reports the expected R version
    And the session is cleaned up
