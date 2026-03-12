# Authentication

VIP tests that verify login flows and authenticated functionality need user
credentials.  How you provide them depends on the deployment's identity
provider.

## Password / LDAP / Keycloak (headless)

Set credentials via environment variables and run normally:

```bash
export VIP_TEST_USERNAME="test-user"
export VIP_TEST_PASSWORD="test-password"
uv run pytest
```

For deployments with Keycloak, `vip verify` handles this automatically —
it provisions a test user and passes credentials to VIP.

## Okta / external OIDC provider (interactive)

External identity providers require a real browser login.  Use
`--interactive-auth` to launch a visible browser, authenticate through the
IdP, and then run the remaining tests headlessly with the captured session:

```bash
uv run pytest --interactive-auth
```

This will:

1. Open a Chromium window and navigate to the Connect login page
2. Wait for you to complete the OIDC login flow (Okta, Azure AD, etc.)
3. Navigate the Connect UI to mint a temporary API key (`_vip_interactive`)
4. Capture the browser session state (cookies, localStorage)
5. Close the browser and run all tests headlessly
6. Delete the API key when the session finishes

Both Playwright browser tests (using the saved session state) and httpx API
tests (using the minted key) work with a single interactive login.

> **Note**: `--interactive-auth` is not available in container/CI
> environments.  For automated runs against OIDC deployments, pre-provision
> credentials and set the environment variables above.
