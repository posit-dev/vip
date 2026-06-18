@connect @if_applicable @api_auth
Feature: Connect embedded Chronicle
  As a Posit Team administrator
  I want to verify that Connect's embedded Chronicle subprocess is running
  So that I know usage data collection actually came up after enabling it

  # Chronicle runs as a supervised subprocess inside Connect. The
  # GET /__api__/v1/system/chronicle endpoint (admin-only) reports whether
  # Chronicle is enabled in the server config and whether the subprocess is
  # running and ready to accept work. VIP verifies that a deployment which
  # declares Chronicle enabled reports both.

  Scenario: Chronicle reports enabled and ready
    Given Connect is accessible at the configured URL
    And Chronicle usage data collection is enabled
    When I query the Chronicle status endpoint
    Then Chronicle reports it is enabled
    And Chronicle reports it is ready
