@security
Feature: Secure storage of secrets and tokens
  As a Posit Team administrator
  I want to verify that secrets and tokens are stored securely
  So that credentials are not exposed

  Scenario: API keys are not stored in the VIP config file
    Given a VIP configuration file is in use
    When I inspect the configuration file contents
    Then no plaintext API keys or passwords are present in the file

  Scenario: Connect API key is provided via environment variable
    Given Connect is configured with an API key
    Then the API key was loaded from the VIP_CONNECT_API_KEY environment variable
