@connect @if_applicable
Feature: Connect email delivery
  As a Posit Team administrator
  I want to verify that Connect can send emails
  So that scheduled report delivery and notifications work

  Scenario: Connect can send a test email
    Given Connect is accessible at the configured URL
    And email delivery is enabled
    When I send a test email via the Connect API
    Then the email task completes without error
