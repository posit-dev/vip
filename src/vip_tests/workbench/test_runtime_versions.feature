@workbench
Feature: Workbench R runtime version
  As a Posit Team administrator
  I want to verify that a launched session runs an expected R version
  So that users get the correct runtime

  Scenario: Launched RStudio session reports an expected R version
    Given the user is logged in to Workbench
    And expected R versions are specified in vip.toml
    When the user starts a new RStudio session
    Then the session transitions to Active state
    And the RStudio console reports the expected R version
    And the session is cleaned up
