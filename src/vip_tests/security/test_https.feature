@security
Feature: HTTPS enforcement
  As a Posit Team administrator
  I want to verify that HTTPS is enforced across all products
  So that traffic is encrypted in transit

  Scenario Outline: <product> enforces HTTPS
    Given <product> is configured with an HTTPS URL
    When I make an HTTP request to <product>
    Then the connection is refused or redirected to HTTPS

    @requires_connect
    Examples:
      | product         |
      | Connect         |

    @requires_workbench
    Examples:
      | product         |
      | Workbench       |

    @requires_package_manager
    Examples:
      | product         |
      | Package Manager |

  Scenario Outline: <product> response headers are checked for version disclosure
    Given <product> is configured in vip.toml
    When I inspect response headers from <product>
    Then any version information in response headers is reported

    @requires_connect
    Examples:
      | product         |
      | Connect         |

    @requires_workbench
    Examples:
      | product         |
      | Workbench       |

    @requires_package_manager
    Examples:
      | product         |
      | Package Manager |
