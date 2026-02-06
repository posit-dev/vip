@connect
Feature: Connect R and Python versions
  As a Posit Team administrator
  I want to verify that the expected R and Python versions are available
  So that content can be deployed with the correct runtime

  Scenario: Expected R versions are available on Connect
    Given Connect is accessible at the configured URL
    And expected R versions are specified in vip.toml
    When I query Connect for available R versions
    Then all expected R versions are present

  Scenario: Expected Python versions are available on Connect
    Given Connect is accessible at the configured URL
    And expected Python versions are specified in vip.toml
    When I query Connect for available Python versions
    Then all expected Python versions are present
