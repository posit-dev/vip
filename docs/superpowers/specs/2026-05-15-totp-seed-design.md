# TOTP seed support for headless authentication

**Status:** Draft
**Date:** 2026-05-15
**Author:** Brian Deitte (with Claude)

## Problem

`vip verify --headless-auth` automates IdP login (Keycloak, Okta) with Playwright using `VIP_TEST_USERNAME` / `VIP_TEST_PASSWORD`. When the IdP issues a TOTP / MFA challenge, the auth flow blocks on an interactive prompt:

- `src/vip/idp.py:75` (Keycloak)
- `src/vip/idp.py:301` (Okta)

```python
code = input(">>> Enter your verification code: ").strip()
```

This blocks every unattended use case: scripted runs, scheduled CI jobs, and any automation where stdin is not a TTY. There is currently no way to feed a TOTP code into VIP non-interactively.

## Goal

Let an automation caller supply a TOTP shared secret (the seed) via an environment variable. VIP generates the current 6-digit code at the moment the IdP requests it, just like an authenticator app does, and fills the field automatically.

## Non-goals

- **K8s job mode (`vip verify --k8s`).** The credential provisioner in `src/vip/verify/credentials.py` does not capture or generate TOTP seeds when it provisions a Keycloak service account. Plumbing the seed through that flow is a separate concern and deserves its own spec when needed.
- **Non-TOTP MFA factors.** Push, SMS, security keys, and Okta Verify push are out of scope.
- **Host-clock skew handling.** TOTP requires the host clock to be within ~30 seconds of the IdP. This is a deployment concern, not a VIP feature; we mention it in troubleshooting docs only.
- **CLI flag for the seed.** A CLI flag would leak the seed into `ps` output and shell history. Env var only.
- **vip.toml field for the seed.** A config field would tempt users to check the seed into version control. Env var only.

## Security framing

The TOTP seed is a long-lived shared secret that is equivalent to a permanent bypass of 2FA for the account it belongs to. Anyone with the seed can generate valid codes indefinitely.

**This feature is intended exclusively for dedicated test service accounts** — IdP users created specifically for VIP runs, isolated from real-user accounts, and provisioned with only the access the test suite requires. Using a personal IdP account's TOTP seed here would defeat the point of having 2FA on that account.

Operational guardrails baked into the design:

- The seed lives only in `VIP_TEST_TOTP_SECRET`, the same shape as `VIP_TEST_PASSWORD`. It belongs in the same secret store and rotation schedule.
- The seed and the generated code are never logged (not even under `--verbose`), never appear in error messages, and never appear in the JSON report or HTML report.
- Documentation surfaces the warning in two places: the README auth section and the `--headless-auth` CLI `--help` text.

## Design

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  vip verify --headless-auth                                  │
│                                                              │
│   cli.py ──► auth.start_headless_auth()                      │
│              │                                               │
│              ├─ totp.validate_secret()  ← fails fast here   │
│              │   if seed is set but unparseable             │
│              │                                               │
│              └─ Playwright launches, drives IdP form        │
│                  │                                          │
│                  └─ idp._fill_*_login()                     │
│                      │                                      │
│                      └─ totp.get_code(prompt) ←─── env set: │
│                                                  pyotp.now()│
│                                                  env unset: │
│                                                  input()    │
└──────────────────────────────────────────────────────────────┘
```

### New module: `src/vip/totp.py`

Two public functions and one env var name. ~40 lines.

```python
"""Generate TOTP codes from a shared secret for automated MFA flows.

Reads VIP_TEST_TOTP_SECRET (a base32-encoded TOTP seed) and produces
the current 6-digit code on demand. Designed for unattended runs
against dedicated test service accounts ONLY.
"""

import os

import pyotp

ENV_VAR = "VIP_TEST_TOTP_SECRET"


def validate_secret(secret: str) -> None:
    """Raise AuthConfigError if *secret* is not a usable base32 TOTP seed.

    Called from start_headless_auth before Playwright launches, so a bad
    seed fails fast with a clear error instead of mid-login.
    """
    # Lazy import: auth.py imports this module, so a top-level import
    # of AuthConfigError would create a circular import. idp.py uses
    # the same pattern.
    from vip.auth import AuthConfigError

    try:
        pyotp.TOTP(secret).now()
    except Exception as exc:
        raise AuthConfigError(
            f"{ENV_VAR} is not a valid base32 TOTP seed: {exc}"
        ) from exc


def get_code(prompt: str = ">>> Enter your verification code: ") -> str:
    """Return a TOTP code: from VIP_TEST_TOTP_SECRET if set, else stdin."""
    secret = os.environ.get(ENV_VAR, "").strip()
    if secret:
        return pyotp.TOTP(secret).now()
    return input(prompt).strip()
```

The code is generated **just-in-time** at the call site (when the IdP's TOTP input is visible), not at startup. This keeps the 30-second validity window starting as late as possible regardless of how slow the IdP page is.

### Touch points

| File | Change |
|---|---|
| `src/vip/totp.py` | New module (above). |
| `src/vip/idp.py` line ~75 (Keycloak) | Replace `input(...)` with `totp.get_code(...)`. |
| `src/vip/idp.py` line ~301 (Okta) | Same. |
| `src/vip/auth.py` `start_headless_auth` | Early call to `totp.validate_secret(...)` if `VIP_TEST_TOTP_SECRET` is set. |
| `pyproject.toml` | Add `pyotp ~= 2.9` to dependencies. |
| `selftests/test_totp.py` | New selftest file. |
| `docs/authentication.md` | Add a "TOTP seed for automation" subsection with the security warning. |
| `src/vip/cli.py` | Update `--headless-auth` help text to mention `VIP_TEST_TOTP_SECRET` and point at the docs. |
| `CLAUDE.md` | List `VIP_TEST_TOTP_SECRET` alongside the other secret env vars. |
| `vip.toml.example` | A comment near the auth section noting the env var (no toml field, just a pointer). |

### Behavior

| `VIP_TEST_TOTP_SECRET` | IdP MFA challenge? | Outcome |
|---|---|---|
| Unset | No | Login proceeds. Unchanged from today. |
| Unset | Yes | Interactive `input()` prompt. Unchanged from today. |
| Set, valid base32 | No | Login proceeds; seed unused. |
| Set, valid base32 | Yes | `pyotp.TOTP(secret).now()` fills the field. No prompt. |
| Set, invalid base32 | n/a | `AuthConfigError` at startup, before Playwright launches. |
| Set, IdP rejects the code | n/a | Existing form-error / timeout path surfaces the failure. No retry — a rejected code usually means clock skew or wrong account. |

A `_log_verbose` line at the fill site reads "auto-filling TOTP code from `VIP_TEST_TOTP_SECRET`" (the env var name only — never the seed or the code).

### Out-of-flow behavior

- The seed is not loaded into `VIPConfig`. It is read directly from the environment by `totp.py` at the moment it is needed. This keeps it out of any debug dumps or serialized state.
- The seed never appears in `pytest` output, the JSON report, or the HTML report.
- If `pyotp` is not installed (shouldn't happen after `uv sync`), the import error message in `totp.py` tells the user to run `uv sync`.

## Testing

### Selftests (`selftests/test_totp.py`)

Run with the existing CI selftest suite, no external services.

1. **Known-vector generation.** Use an RFC 6238 test seed and a frozen time (monkey-patch `pyotp.TOTP.now` or use `freezegun`); assert the returned code matches the published vector.
2. **Invalid base32 rejected.** `validate_secret("not-base32-!!")` raises `AuthConfigError` with a message naming `VIP_TEST_TOTP_SECRET`.
3. **Env-var unset falls back to `input()`.** Monkeypatch `builtins.input`; assert it is called with the supplied prompt and the returned value is stripped.
4. **Env-var set bypasses `input()`.** Monkeypatch `builtins.input` to raise; with `VIP_TEST_TOTP_SECRET` set, `get_code()` must return a generated code without invoking `input`.
5. **Seed and code never logged.** Capture stdout in tests 1 and 4; assert neither the seed nor the generated code appears.

### Showboat demo

A `demo.md` that exercises:
- The known-vector generation test (deterministic output).
- The selftest suite passing (`uv run pytest selftests/test_totp.py -v`, with the timing suffix stripped per CLAUDE.md guidance).
- `just check` clean.

The end-to-end path (real IdP) cannot run in CI; this is the same constraint as every other product test in VIP and is acknowledged, not solved.

### Manual verification (developer-time, not committed)

Against a Keycloak or Okta tenant where a test service account has TOTP enabled and you hold the seed:

1. `export VIP_TEST_TOTP_SECRET=<base32>`
2. `uv run vip verify --headless-auth --connect-url ...`
3. Confirm the login completes without a prompt.

## Error handling

- **Invalid base32 seed:** `AuthConfigError` raised before Playwright launches. Message names `VIP_TEST_TOTP_SECRET`.
- **IdP rejects the generated code:** existing IdP form-error / 30-second `start_headless_auth` timeout path surfaces the failure with the IdP's error text (Okta) or a generic Keycloak failure message. No automatic retry — the only common cause is host-clock skew, and silently retrying would hide it.
- **`pyotp` import failure:** module-level `ImportError`; user runs `uv sync`. Not a runtime concern after `uv sync`, which CI enforces.
- **Env var set to whitespace:** `secret.strip()` produces empty; `get_code()` falls through to the interactive prompt. (Treat an empty seed as "not set" rather than as a hard error — robust to half-empty `.envrc` files.)

## Open questions

None at this time.

## Future work (not in this spec)

- K8s job mode: `verify/credentials.py` would need to either accept a user-supplied seed via env passthrough or generate one when provisioning the Keycloak test user, then write it into the Job's Secret. Separate spec.
- Non-TOTP factors (push, SMS, security keys): would require IdP-specific handling per factor; not on any current roadmap.
