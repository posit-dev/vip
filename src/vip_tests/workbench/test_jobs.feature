@workbench
Feature: Workbench job execution

  Scenario: Background Job runs and completes
    Given the user is logged in to Workbench
    When the user starts a new RStudio Pro session for a job test
    And the session reaches Active state
    And the user joins the RStudio Pro session
    And the RStudio IDE loads successfully
    And the user writes a test R script file via the console
    And the user runs the script as a Background Job
    Then the Background Job completes with expected output
    And the job test session is cleaned up

  Scenario: Workbench Job runs and completes
    Given the user is logged in to Workbench
    When the user starts a new RStudio Pro session for a job test
    And the session reaches Active state
    And the user joins the RStudio Pro session
    And the RStudio IDE loads successfully
    And the user writes a test R script file via the console
    And the user runs the script as a Workbench Job
    Then the Workbench Job completes with expected output
    And the job test session is cleaned up
