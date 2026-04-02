@workbench
Feature: Session launch capacity
  As a Posit Team administrator
  I want to verify that the deployment can handle multiple concurrent sessions
  So that I can validate capacity for my expected user base

  Scenario Outline: Launch <count> sessions with <profile> resource profile
    Given Workbench is accessible and I am logged in
    When I launch <count> sessions with the <profile> resource profile
    Then all <count> sessions reach Active state
    And I clean up all launched sessions

    Examples:
      | count | profile |
      | 3     | Small   |
      | 3     | Medium  |

  Scenario: Launch sessions with default resource profile
    Given Workbench is accessible and I am logged in
    When I launch 3 sessions with the default resource profile
    Then all 3 sessions reach Active state
    And I clean up all launched sessions
