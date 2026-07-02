# CI: Mock-IdP E2E stack for OIDC auth testing

*2026-07-01T22:55:07Z by Showboat 0.6.1*
<!-- showboat-id: 1eab74d4-c95b-4f49-8d07-b2d80c182f22 -->

This adds Child A of issue #409 (posit-dev/vip#419): a real, seeded Keycloak realm that fronts Connect and Workbench over OIDC, plus a new gated CI workflow (.github/workflows/mock-idp-e2e.yml) that runs `vip verify --headless-auth --idp keycloak` against both products with no customer IdP involved.

New files:
- `docker/keycloak/realm-vip.json` -- seeded realm with OIDC clients for Connect and Workbench, and a test user with a TOTP credential.
- `docker/tls/gen-certs.sh` -- generates one throwaway CA + leaf certs, because both Connect's `OpenIDConnectIssuer` and Workbench's `auth-openid-issuer` reject self-signed/HTTP issuers.
- `docker/connect/Dockerfile.oidc` + `entrypoint-oidc.sh` + `rstudio-connect-oidc.gcfg` -- Connect OIDC wiring (Connect has no cont-init.d hook, so this overrides ENTRYPOINT to trust the CA first).
- `docker/workbench/oidc-init.sh` -- Workbench OIDC wiring via the existing cont-init.d mechanism.
- `compose.mock-idp.yml` -- wires the whole stack together on one Docker network.
- `.github/workflows/mock-idp-e2e.yml` -- the new CI workflow.

--interactive-auth E2E automation is deferred to a follow-up (it requires driving a second browser process concurrently with a blocked `vip verify` call); the interactive-auth state machine already has unit coverage in `selftests/test_auth.py`.

This demo runs the standard verification suite. Docker/compose commands are intentionally excluded from this demo -- they were verified manually (Keycloak realm import + a real Playwright login against the seeded realm succeeded) but container startup output isn't deterministic enough for `showboat verify` to re-run cleanly.

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
144 files already formatted
```

```bash
uv run mypy src/vip/
```

```output
src/vip/load_users.py:124: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
src/vip/load_users.py:125: note: By default the bodies of untyped functions are not checked, consider using --check-untyped-defs  [annotation-unchecked]
Success: no issues found in 27 source files
```

```bash
uv run pytest selftests/ --ignore=selftests/test_load_engine.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
805 passed, 22 warnings
```

```bash
uvx zizmor==1.24.1 --config .github/zizmor.yml .github/workflows/mock-idp-e2e.yml
```

```output
 INFO zizmor: 🌈 zizmor v1.24.1
 INFO audit: zizmor: 🌈 completed .github/workflows/mock-idp-e2e.yml
No findings to report. Good job! (5 suppressed)
```
