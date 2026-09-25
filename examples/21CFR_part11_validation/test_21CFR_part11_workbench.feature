@workbench
Feature: 21 CFR Part 11 flavoured controls for Workbench
  As a validation lead in a regulated environment
  I want evidence that interactive analysis is limited to authorised individuals
  So that the work behind a record can be attributed to an account

  @control-access-control-session-api
  Scenario: An unauthenticated caller cannot reach the session API
    Given Workbench is accessible at the configured URL
    When I request the Workbench session API without credentials
    Then the request is refused

  @control-access-control-authorised-caller
  Scenario: An authorised caller can reach the session API
    Given Workbench is accessible at the configured URL
    When I request the Workbench session API with the test credentials
    Then a session listing is returned
