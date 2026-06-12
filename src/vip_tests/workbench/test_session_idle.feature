@workbench @performance
Feature: Workbench idle session auto-suspend behavior

  Scenario: Idle session auto-suspends after the configured timeout
    Given the configured idle timeout is known
    And the configured idle grace window is known
    And the user is logged in to Workbench for idle test
    When the user starts a new RStudio Pro session for idle testing
    And the session reaches Active state for idle testing
    And the user leaves the session idle
    Then the session auto-suspends within the expected window

  Scenario: Active session is not suspended while work is running
    Given the configured idle timeout is known
    And the configured idle grace window is known
    And the user is logged in to Workbench for idle test
    When the user starts a new RStudio Pro session for idle testing
    And the session reaches Active state for idle testing
    And the user joins the session to perform work
    And a long-running computation keeps the session active
    Then the session remains Active at the end of the activity window
    And the active idle session is cleaned up
