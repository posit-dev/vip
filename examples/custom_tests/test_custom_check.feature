Feature: Custom site-specific check
  As a customer administrator
  I want to run a site-specific validation check
  So that I can verify my own deployment responds as expected

  This is the "minimal" scaffold template: one scenario, checking your own
  configured Connect deployment rather than a hardcoded address. Copy this
  pattern -- a Scenario here, matching Given/When/Then steps in
  test_custom_check.py -- to add more checks.

  # The @connect tag is what makes VIP's auto-skip contract work for this
  # scenario: when [connect] isn't configured in vip.toml, VIP deselects it
  # instead of failing with no client to talk to. It has to be paired with
  # the equivalent @pytest.mark.connect decorator in test_custom_check.py --
  # see that file for why both are needed.
  @connect
  Scenario: Custom endpoint responds successfully
    Given I have a custom endpoint to verify
    When I request the custom endpoint
    Then it responds successfully
