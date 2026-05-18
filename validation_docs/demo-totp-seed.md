# Feature: TOTP seed support for headless auth

*2026-05-15T21:48:20Z by Showboat 0.6.1*
<!-- showboat-id: 635d6336-1928-4cf1-8929-0580f69d627d -->

Adds VIP_TEST_TOTP_SECRET so unattended --headless-auth runs can satisfy MFA without prompting. Designed for dedicated TEST SERVICE ACCOUNTS only — the seed is equivalent to bypassing 2FA.

```bash
uv run python -c 'import pyotp; pyotp.TOTP("JBSWY3DPEHPK3PXP").now(); print("ok")'
```

```output
ok
```

Deterministic code generation — same seed + same 30-second window yields the same 6-digit code. VIP uses this same mechanism at the IdP fill site.

```bash
uv run pytest selftests/test_totp.py -v 2>&1 | grep -oE 'selftests/[^ ]+ PASSED|selftests/[^ ]+ FAILED|selftests/[^ ]+ ERROR' | sort
```

```output
selftests/test_totp.py::TestGetCode::test_env_empty_falls_back_to_input PASSED
selftests/test_totp.py::TestGetCode::test_env_set_matches_pyotp_reference PASSED
selftests/test_totp.py::TestGetCode::test_env_set_returns_generated_code PASSED
selftests/test_totp.py::TestGetCode::test_env_unset_calls_input PASSED
selftests/test_totp.py::TestValidateSecret::test_empty_string_raises PASSED
selftests/test_totp.py::TestValidateSecret::test_invalid_base32_raises_auth_config_error PASSED
selftests/test_totp.py::TestValidateSecret::test_valid_base32_passes PASSED
```

```bash
uv run pytest selftests/test_auth.py::TestStartHeadlessAuthValidation -v 2>&1 | grep -oE 'selftests/[^ ]+ PASSED|selftests/[^ ]+ FAILED|selftests/[^ ]+ ERROR' | sort
```

```output
selftests/test_auth.py::TestStartHeadlessAuthValidation::test_invalid_totp_seed_raises_before_playwright PASSED
selftests/test_auth.py::TestStartHeadlessAuthValidation::test_no_urls_raises_even_with_warm_cache PASSED
selftests/test_auth.py::TestStartHeadlessAuthValidation::test_no_urls_raises_without_cache PASSED
selftests/test_auth.py::TestStartHeadlessAuthValidation::test_valid_totp_seed_passes_validation PASSED
```

```bash
uv run pytest selftests/test_idp.py -v 2>&1 | grep -oE 'selftests/[^ ]+ PASSED|selftests/[^ ]+ FAILED|selftests/[^ ]+ ERROR' | sort
```

```output
selftests/test_idp.py::TestGetIdpStrategy::test_case_insensitive_lookup PASSED
selftests/test_idp.py::TestGetIdpStrategy::test_keycloak_returns_callable PASSED
selftests/test_idp.py::TestGetIdpStrategy::test_okta_returns_callable PASSED
selftests/test_idp.py::TestGetIdpStrategy::test_supported_idps_contains_expected PASSED
selftests/test_idp.py::TestGetIdpStrategy::test_unknown_idp_raises PASSED
selftests/test_idp.py::TestKeycloakUsesTotpGetCode::test_keycloak_calls_totp_get_code_not_input PASSED
selftests/test_idp.py::TestOktaUsesTotpGetCode::test_okta_calls_totp_get_code_not_input PASSED
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
129 files already formatted
```

End-to-end IdP verification cannot run in CI (no Posit products available) — same constraint as every other product test in VIP. Manual verification: export VIP_TEST_TOTP_SECRET=<base32> and run vip verify --headless-auth against an MFA-enabled tenant.
