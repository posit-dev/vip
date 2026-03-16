@security
Feature: API error handling
  As a Posit Team administrator
  I want to verify that the API returns correct error responses
  So that authentication failures and bad requests are handled correctly

  Scenario: Unauthenticated API request returns 401
    Given Connect is configured in vip.toml
    When I make an unauthenticated API request to Connect
    Then the response status is 401

  Scenario: Invalid API key returns 401
    Given Connect is configured in vip.toml
    When I make an API request to Connect with an invalid key
    Then the response status is 401

  Scenario: Non-existent endpoint returns 404
    Given Connect is configured in vip.toml
    When I request a non-existent endpoint on Connect
    Then the response status is 404
