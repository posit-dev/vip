@workbench
Feature: Workbench session management

  Scenario: Session can be suspended and resumed
    Given the user is logged in to Workbench
    When the user starts a new RStudio Pro session
    And the session reaches Active state
    And the user suspends the session
    Then the session reaches Suspended state
    When the user resumes the session
    Then the session reaches Active state again
    And the session is cleaned up
