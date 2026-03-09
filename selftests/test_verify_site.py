"""Tests for Site CR parsing and vip.toml generation.

Transfused from PTD's cmd/internal/verify/verify_test.go.
"""

from __future__ import annotations

import pytest

from vip.verify.site import _build_product_url, generate_vip_config


def test_generate_config_nil_site():
    """Empty site CR should raise ValueError."""
    with pytest.raises(ValueError, match="site_cr cannot be empty"):
        generate_vip_config({}, "test")


def test_generate_config_connect_only():
    """Site with only Connect enabled should generate correct config."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {
                "auth": {"type": "saml"},
            },
        }
    }

    config = generate_vip_config(site, "my-deployment")

    assert config != ""
    # Auth provider should come from Connect when present
    assert 'provider = "saml"' in config
    # Connect should be enabled with the correct URL
    assert 'url = "https://connect.example.com"' in config
    # Workbench section should be present (disabled)
    assert "[workbench]" in config
    assert "enabled = false" in config


def test_generate_config_auth_provider_precedence():
    """Connect auth takes precedence over Workbench auth."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {
                "auth": {"type": "saml"},
            },
            "workbench": {
                "auth": {"type": "ldap"},
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'provider = "saml"' in config


def test_generate_config_workbench_auth_fallback():
    """When Connect has no auth spec, fall back to Workbench auth."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {},
            "workbench": {
                "auth": {"type": "ldap"},
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'provider = "ldap"' in config


def test_generate_config_default_auth():
    """When no product has an auth spec, default to oidc."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {},
        }
    }

    config = generate_vip_config(site, "test")

    assert 'provider = "oidc"' in config


def test_generate_config_custom_domain_prefix():
    """Custom domainPrefix should be used in URL construction."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {
                "domainPrefix": "rsconnect",
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'url = "https://rsconnect.example.com"' in config


def test_generate_config_empty_auth_type():
    """Auth.Type == "" should fall through to the default "oidc"."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {
                "auth": {"type": ""},
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'provider = "oidc"' in config


def test_generate_config_empty_domain():
    """Empty domain with a product that has no per-product baseDomain should return an error."""
    site = {
        "spec": {
            "domain": "",
            "connect": {},
        }
    }

    with pytest.raises(
        ValueError,
        match=(
            "site domain is required when products are configured without a per-product baseDomain"
        ),
    ):
        generate_vip_config(site, "test")


def test_generate_config_empty_domain_all_base_domains():
    """Empty site-level domain is valid when every product has its own baseDomain."""
    site = {
        "spec": {
            "domain": "",
            "connect": {
                "baseDomain": "custom.org",
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'url = "https://connect.custom.org"' in config


def test_generate_config_base_domain_with_subdomain_produces_double_prefix():
    """If BaseDomain is mistakenly set to a fully-qualified hostname, double-prefix URL results.

    This test documents that footgun so the behaviour is explicit and visible.
    """
    site = {
        "spec": {
            "domain": "",
            "connect": {
                "baseDomain": "connect.custom.org",
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'url = "https://connect.connect.custom.org"' in config


def test_build_product_url_base_domain_override():
    """BaseDomain in product spec should override site domain."""
    spec = {
        "baseDomain": "custom.org",
    }
    got = _build_product_url(spec, "connect", "example.com")
    want = "https://connect.custom.org"
    assert got == want


def test_build_product_url_domain_prefix_and_base_domain():
    """Both DomainPrefix and BaseDomain should be used together."""
    spec = {
        "domainPrefix": "rsc",
        "baseDomain": "custom.org",
    }
    got = _build_product_url(spec, "connect", "example.com")
    want = "https://rsc.custom.org"
    assert got == want


def test_build_product_url_none_spec():
    """None product spec with valid base domain should use default prefix."""
    got = _build_product_url(None, "connect", "example.com")
    want = "https://connect.example.com"
    assert got == want


def test_build_product_url_none_spec_empty_domain():
    """None product spec with empty base domain should return empty string."""
    got = _build_product_url(None, "connect", "")
    assert got == ""


def test_build_product_url_empty_domain():
    """Product spec with empty baseDomain and empty site domain should return empty string."""
    spec = {}
    got = _build_product_url(spec, "connect", "")
    assert got == ""


def test_generate_config_all_products():
    """Site with all products enabled should generate complete config."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {
                "auth": {"type": "oidc"},
            },
            "workbench": {},
            "packageManager": {},
        }
    }

    config = generate_vip_config(site, "test-deployment")

    # Check general section
    assert "[general]" in config
    assert 'deployment_name = "test-deployment"' in config

    # Check all products are enabled
    assert "[connect]" in config
    assert 'url = "https://connect.example.com"' in config
    assert "[workbench]" in config
    assert 'url = "https://workbench.example.com"' in config
    assert "[package_manager]" in config
    assert 'url = "https://packagemanager.example.com"' in config

    # Check auth
    assert "[auth]" in config
    assert 'provider = "oidc"' in config

    # Check disabled features
    assert "[email]" in config
    assert "[monitoring]" in config
    assert "[security]" in config


def test_generate_config_mixed_domain_configs():
    """Products with mixed baseDomain and site domain should work correctly."""
    site = {
        "spec": {
            "domain": "example.com",
            "connect": {
                "baseDomain": "connect-custom.com",
            },
            "workbench": {},  # Should use site domain
            "packageManager": {
                "domainPrefix": "pkg-custom",
            },
        }
    }

    config = generate_vip_config(site, "test")

    assert 'url = "https://connect.connect-custom.com"' in config
    assert 'url = "https://workbench.example.com"' in config
    assert 'url = "https://pkg-custom.example.com"' in config


def test_generate_config_workbench_only():
    """Site with only Workbench should work correctly."""
    site = {
        "spec": {
            "domain": "example.com",
            "workbench": {
                "auth": {"type": "saml"},
            },
        }
    }

    config = generate_vip_config(site, "test")

    # Connect should be disabled
    assert "[connect]" in config
    assert "enabled = false" in config

    # Workbench should be enabled
    assert "[workbench]" in config
    assert "enabled = true" in config
    assert 'url = "https://workbench.example.com"' in config

    # Auth should come from Workbench
    assert 'provider = "saml"' in config


def test_generate_config_package_manager_only():
    """Site with only Package Manager should work correctly."""
    site = {
        "spec": {
            "domain": "example.com",
            "packageManager": {},
        }
    }

    config = generate_vip_config(site, "test")

    # Connect and Workbench should be disabled
    assert "[connect]" in config
    assert "[workbench]" in config

    # Package Manager should be enabled
    assert "[package_manager]" in config
    assert "enabled = true" in config
    assert 'url = "https://packagemanager.example.com"' in config

    # Auth should default to oidc (Package Manager doesn't provide auth)
    assert 'provider = "oidc"' in config


def test_build_product_url_empty_prefix_uses_default():
    """Empty domainPrefix should fall back to default prefix."""
    spec = {
        "domainPrefix": "",
    }
    got = _build_product_url(spec, "connect", "example.com")
    want = "https://connect.example.com"
    assert got == want
