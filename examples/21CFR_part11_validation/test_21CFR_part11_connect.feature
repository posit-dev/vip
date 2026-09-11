@connect
Feature: 21 CFR Part 11 flavoured controls
  As a validation lead in a regulated environment
  I want automated evidence for the controls that can be automated
  So that my traceability matrix is generated rather than hand-maintained

  @control-audit-trail-publish
  Scenario: Publishing content is recorded with an actor and a timestamp
    Given Connect is accessible at the configured URL
    When I list recent audit log entries
    Then each entry records an actor and a timestamp

  @control-access-control-privileged-action
  Scenario: A privileged action requires authorisation
    Given Connect is accessible at the configured URL
    When I request a privileged administrative endpoint without credentials
    Then the request is refused

  @control-record-retention
  Scenario: The audit log does not offer a deletion method
    Given Connect is accessible at the configured URL
    When I ask which methods the audit log endpoint allows
    Then deletion is not among them
