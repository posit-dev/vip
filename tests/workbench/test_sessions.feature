@workbench
Feature: Workbench sessions
  As a Posit Team administrator
  I want to verify that sessions start and persist without errors
  So that users can work reliably

  Scenario: A new session starts and persists
    Given the user is logged in to Workbench
    When the user starts a new session
    And waits for the session to be ready
    Then the session appears in the active sessions list
    And the session has no error status
