Feature: Custom site-specific check
  As a customer administrator
  I want to run site-specific validation checks
  So that I can verify configurations unique to my deployment

  This is an example of a custom test that lives outside the VIP source
  tree.  Place your own .feature and .py files in a directory and point
  VIP at it via the configuration or CLI:

    [general]
    extension_dirs = ["/path/to/this/directory"]

  Or:

    pytest --vip-extensions=/path/to/this/directory

  Scenario: Example custom health check
    Given I have a custom endpoint to verify
    When I request the custom endpoint
    Then it responds successfully
