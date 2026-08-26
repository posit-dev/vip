@prerequisites
Feature: Example failure card (intentional demonstration)
  As someone evaluating a VIP report
  I want to see what a failed check looks like
  So that I can recognize failure details before running VIP against my own deployment

  Scenario: This check intentionally fails to demonstrate failure rendering
    Given a check that is written to fail on purpose
    When the check runs as part of this example report
    Then it fails by design, not because anything is actually broken
