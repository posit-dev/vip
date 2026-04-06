# Plan: Smoke Testing Against Posit Workbench in CI

_Related issue: [#9](https://github.com/posit-dev/vip/issues/9)_

## Background

VIP already validates Connect tests in CI using
[`posit-dev/with-connect`](https://github.com/posit-dev/with-connect) (see
[plans/connect-ci-testing.md](./connect-ci-testing.md) and
`.github/workflows/connect-smoke.yml`).

We need an equivalent CI workflow for Posit Workbench — a minimal smoke test
that validates VIP's Workbench test path against a real, running Workbench
instance without requiring a dedicated deployment.

## Research: Running Workbench in Docker

### Key difference from Connect

Unlike Connect's `posit-dev/with-connect` action, Workbench uses the
**`with-workbench` CLI tool** rather than a GitHub Action.  Install it with:

```bash
uv tool install git+https://github.com/posit-dev/with-workbench.git
```

`with-workbench` handles the full container lifecycle: PAM user provisioning,
health checks, port allocation, and cleanup.  This mirrors the ergonomics of
`with-connect` without requiring a dedicated GitHub Action.

### Workbench Docker image

Posit publishes official Workbench container images:

| Registry | Image |
|---|---|
| Docker Hub | `rstudio/rstudio-workbench` |

Image tags combine an OS suffix with a release version, e.g.
`ubuntu2204-2026.01.1` or its alias `jammy-2026.01.1`.  The mutable
`ubuntu2204` (and `jammy`) tags always point to the latest release.

### Key environment variables

| Variable | Purpose |
|---|---|
| `RSW_LICENSE` | License activation key (required) |
| `RSW_TESTUSER` | Username of the auto-provisioned test user (default: `rstudio`) |
| `RSW_TESTUSER_PASSWD` | Password for the test user — must be ≥ 8 chars to satisfy PAM |
| `RSW_TESTUSER_UID` | UID for the test user (optional) |

The container automatically creates the test user on startup via these env
vars — **no manual `useradd`/`chpasswd` needed**.  Passwords shorter than 8
characters trigger a `BAD PASSWORD: The password is shorter than 8 characters`
PAM error, so always set `RSW_TESTUSER_PASSWD` to a value of 8+ characters.

### Health check and version endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health-check` | Returns `200 OK` when the server is ready |
| `GET /api/server-info` | Returns JSON with `version`, `mode`, etc. |

### Startup time

Workbench takes longer to start than Connect — typically **60–180 seconds** on
a GitHub Actions `ubuntu-latest` runner.  The workflow must poll the health
endpoint with a generous timeout.

### Proven usage pattern

```bash
# Start container (RSW_TESTUSER_PASSWD must be >= 8 chars)
docker run -d \
  --name workbench \
  -p 8787:8787 \
  -e RSW_LICENSE="${LICENSE_KEY}" \
  -e RSW_TESTUSER=rstudio \
  -e RSW_TESTUSER_PASSWD="Rstudio123!" \
  rstudio/rstudio-workbench:ubuntu2204-2026.01.1

# Wait for ready
timeout 180 bash -c 'until curl -sf http://localhost:8787/health-check; do sleep 5; done'

# Resolve version from the running instance via authenticated API call.
# POST /auth-sign-in to get a session cookie, then GET /api/server-info.
curl -s -c /tmp/wb_cookies.txt \
  -d "username=rstudio&password=Rstudio123!&stay_signed_in=0&appUri=" \
  http://localhost:8787/auth-sign-in > /dev/null
RESPONSE=$(curl -s -b /tmp/wb_cookies.txt http://localhost:8787/api/server-info)
VERSION=$(echo "${RESPONSE}" | jq -r '.version // empty')

# Run tests
pytest tests/prerequisites/test_components.py tests/workbench/test_auth.py ...

# Cleanup
docker stop workbench && docker rm workbench || true
```

## What VIP tests can run in Docker Workbench

| Test file | Feasibility | Notes |
|---|---|---|
| `prerequisites/test_components` | ✅ Yes | Health-check only — no auth required |
| `workbench/test_auth` | ✅ Yes | Password form login; uses page objects from `tests/workbench/pages/` |
| `workbench/test_ide_launch` | ✅ Yes | Standard image includes R; RStudio is the default IDE. Other IDEs skip cleanly via availability guard |
| `workbench/test_sessions` | ✅ Yes | Suspend/resume lifecycle using RStudio |
| `workbench/test_packages` | ⚠️ Partial | Skips PM assertion when Package Manager is not configured |
| `workbench/test_data_sources` | ⚠️ Partial | Skips when no data sources are configured |

> **Note:** `test_runtime_versions` was removed from the workbench test suite
> (commit `f45d242` on main). Runtime and session fixtures now live in
> `tests/workbench/conftest.py` and are consumed by `test_ide_launch`.

### Recommended initial test scope

1. **`prerequisites/test_components`** — Workbench health check (no credentials)
2. **`workbench/test_auth`** — Web UI login with the PAM test user
3. **`workbench/test_ide_launch`** — RStudio session launch (R included in standard image)
4. **`workbench/test_sessions`** — Session suspend/resume lifecycle

`test_auth` now uses the page-object selectors in `tests/workbench/pages/`
(e.g. `#posit-logo`, `#current-user`, `button:text-is('New Session')`) — the
same selectors used by rstudio-pro's own end-to-end suite.  It also verifies
that `#current-user` text matches `auth.username` (`rstudio` in the Docker
setup).

Also note: `WorkbenchConfig` (added in `d92a365` on main) now supports an
optional `api_key` field backed by the `VIP_WORKBENCH_API_KEY` environment
variable.  The Docker smoke test uses PAM/password auth, so `api_key` is left
unset.  For deployments with a Workbench API key, set it in `[workbench]`:

```toml
[workbench]
api_key = "..."   # or via VIP_WORKBENCH_API_KEY env var
```

## Implementation plan

### Phase 1: Minimal smoke test workflow (complete)

`.github/workflows/workbench-smoke.yml` was created using the `with-workbench`
CLI tool instead of raw `docker run`.  The CLI is installed in the workflow via:

```yaml
- name: Install with-workbench
  run: uv tool install git+https://github.com/posit-dev/with-workbench.git
```

`with-workbench` then handles container startup, PAM user provisioning, health
polling, and port allocation in a single command.  The workflow generates
`vip.toml` from the outputs (URL, resolved version, credentials) and runs
`pytest` against the live instance.

**Key decisions:**

- **`with-workbench` CLI**: Replaces raw `docker run` + manual `useradd`/`chpasswd`.
  Handles the full lifecycle and exposes structured outputs (URL, version).
- **Version format**: `with-workbench` uses plain version strings (`2026.01.1`,
  `release`) rather than Docker image tags (`ubuntu2204-2026.01.1`).
- **Single version on PRs**: Only `2026.01.1` is tested on push/PR to keep CI
  fast.  The `release` (latest) version is added on scheduled runs to catch
  regressions.
- **Offline schedule offset**: The cron runs at 7am UTC, one hour after the
  Connect smoke run (6am), to avoid resource contention.
- **Generous timeouts**: 180 seconds for container readiness, vs. 60–120 for
  Connect, because Workbench takes longer to boot.
- **Cleanup with `if: always()`**: Container is removed even when tests fail.

### Phase 2: Expand test coverage (complete)

The standard `rstudio/rstudio-workbench` image ships R and Python, so all IDE
and session tests run without a custom image.  The following tests were added to
the smoke workflow beyond the initial `test_components` + `test_auth` scope:

- **`workbench/test_ide_launch`** — Launches an RStudio session (R is available
  in the standard image).  Non-RStudio IDEs (VS Code, JupyterLab, Positron)
  skip cleanly via an IDE availability guard that checks whether the IDE is
  offered by the running instance before attempting to launch it.
- **`workbench/test_sessions`** — Exercises the suspend/resume session lifecycle
  using RStudio.
- **`workbench/test_packages`** — Included with partial coverage: the Package
  Manager assertion is skipped when PM is not configured in `vip.toml`.
- **`workbench/test_data_sources`** — Included with partial coverage: skips
  entirely when no data sources are configured.

### Phase 3: Version matrix and nightly runs (future)

- Test against `daily` (latest nightly Workbench builds) on a separate nightly
  schedule to get early warning of breaking changes.
- Consider a `preview` tag if Posit publishes one.
- Add result upload and diff reporting to surface regressions across versions.

## Prerequisites for implementation

1. **GitHub secret**: A `WORKBENCH_LICENSE` secret containing a valid Posit
   Workbench activation key must be added to the `posit-dev/vip` repository
   (or organization) settings.

2. **Decide on trigger policy**: Running on every PR adds ~3–5 minutes to CI
   due to Workbench's longer startup time.  Consider running only on `main`
   pushes and on a nightly schedule for PRs.

## Open questions

1. **License format**: The license key is passed as the `RSW_LICENSE` env var
   (plain activation key string).  If only a license file is available, mount
   it at `/var/lib/rstudio-server/*.lic` and use `RSW_LICENSE_FILE_PATH` instead.

2. **Image availability**: Are all required version tags available on Docker
   Hub for `rstudio/rstudio-workbench`?  Some older versions may only exist in
   a private registry.

3. **UI selector accuracy**: ~~The Playwright selectors in `test_auth.py` use the
   page-object classes in `tests/workbench/pages/` — mirroring the rstudio-pro
   e2e selectors (`#posit-logo`, `#current-user`, etc.).  They should be accurate
   for the 2026.01 image but may need adjustment for older releases.~~
   **Resolved**: Selectors (`#posit-logo`, `#current-user`, `button:text-is('New Session')`)
   work correctly with the standard Docker image.

4. **Session support**: ~~The Workbench Docker image includes two versions of R
   and two versions of Python (per Docker Hub docs), so IDE launch tests should
   work once Phase 2 is implemented.~~
   **Resolved**: The standard image includes R and Python.  IDE launch and session
   tests (`test_ide_launch`, `test_sessions`) both work against the unmodified image.

5. **`/api/server-info` authentication**: The Workbench `/api/server-info` endpoint
   requires authentication. Version resolution uses `POST /auth-sign-in` to get a
   session cookie, then `GET /api/server-info` with that cookie.  This also
   validates that password auth is working before the Playwright tests run.
