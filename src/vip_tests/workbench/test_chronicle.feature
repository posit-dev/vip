@workbench
Feature: Workbench Chronicle observability
  As a Posit Team administrator
  I want to verify that Chronicle is collecting Workbench telemetry
  So that I know the observability pipeline is actually producing usable data

  Chronicle stores telemetry on the Workbench server and has no query API. It
  writes raw chunk files to its storage path as it scrapes, compacting them into
  the daily/curated datasets only much later. The only timely way to prove it is
  collecting is to read those raw chunk files back. This test launches an RStudio
  session and, inside it, reads Chronicle's raw chunk files to confirm it has
  written queryable telemetry for its two deterministically collected paths.
  Reading in-session also proves the session user can read the data directory.

  Enabling [chronicle] enabled requires chronicle-enabled=1, metrics-enabled=1,
  and workbench-api-admin-enabled=1 in rserver.conf (see vip.toml.example).

  Scenario: Chronicle has collected telemetry readable in-session
    Given the user is logged in to Workbench
    And Chronicle verification is enabled in vip.toml
    When the user starts a new RStudio session
    And the session transitions to Active state
    And the RStudio IDE is displayed and functional
    Then Chronicle has collected runtime metrics via the Prometheus scrape
    And Chronicle has collected user information via the Workbench admin API
    And the session is cleaned up
