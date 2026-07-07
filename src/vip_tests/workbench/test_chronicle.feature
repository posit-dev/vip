@workbench
Feature: Workbench Chronicle observability
  As a Posit Team administrator
  I want to verify that Chronicle is collecting Workbench telemetry
  So that I know the observability pipeline is actually producing usable data

  Chronicle stores telemetry as Parquet files on the Workbench server; it has
  no query API. The only way to prove it is collecting is to read that data.
  This test launches an RStudio session and, inside it, uses the
  chronicle.reports R package to confirm Chronicle has written queryable data
  for each of its three collection paths. Launching the session exercises the
  pipeline by generating fresh session telemetry.

  Enabling chronicle_enabled asserts full Chronicle functionality: all three
  collection paths must be configured and producing data (see vip.toml.example
  for the required rserver.conf / chronicle-local.gcfg settings per path).

  Scenario: Chronicle has collected telemetry across all three paths
    Given the user is logged in to Workbench
    And Chronicle verification is enabled in vip.toml
    When the user starts a new RStudio session
    And the session transitions to Active state
    And the RStudio IDE is displayed and functional
    Then Chronicle has collected runtime metrics via the Prometheus scrape
    And Chronicle has collected user information via the Workbench admin API
    And Chronicle has collected session events via OTLP
    And the session is cleaned up
