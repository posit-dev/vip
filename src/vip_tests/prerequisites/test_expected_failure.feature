@prerequisites
Feature: Expected failure for report demonstration
  As a VIP developer
  I want to see what a failed test looks like in the report
  So that I can verify the report renders failures correctly

  Scenario: Workbench server is reachable but not configured
    Given Workbench is expected to be configured
    When I check the Workbench configuration
    Then Workbench should be reachable
