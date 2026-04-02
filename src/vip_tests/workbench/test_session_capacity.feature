@workbench
Feature: Session launch capacity
  As a Posit Team administrator
  I want to verify that the deployment can handle multiple concurrent sessions
  So that I can validate capacity for my expected user base

  Scenario: Launch sessions with the configured resource profile
    Given Workbench is accessible and I am logged in
    When I launch sessions with the test resource profile
    Then all launched sessions reach Active state
    And I clean up all launched sessions
