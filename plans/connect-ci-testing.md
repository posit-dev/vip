# Plan: Smoke Testing Against Connect in CI

_Related issue: [#2](https://github.com/posit-dev/vip/issues/2)_

## Background

VIP currently runs lint and selftests in CI, but product tests (Connect,
Workbench, Package Manager) only run against real deployments. We need CI
validation that our Connect tests actually work against a running Connect
instance, at least for a minimal subset of tests.

[@jonkeane](https://github.com/jonkeane) recommended using
[`posit-dev/with-connect`](https://github.com/posit-dev/with-connect) to
spin up Connect in Docker for CI testing.

## Research: `posit-dev/with-connect`

### What it does

`with-connect` is a CLI tool and GitHub Action that:

1. Pulls a Posit Connect Docker image (version-configurable)
2. Starts a container with a license file mounted
3. Waits for Connect to start and bootstraps an admin API key
4. Either runs a command with `CONNECT_API_KEY` and `CONNECT_SERVER`
   set, or outputs those values for use in subsequent workflow steps
5. Stops the container when done

### GitHub Action interface

**Inputs:**

| Input         | Required | Default   | Description                                          |
|---------------|----------|-----------|------------------------------------------------------|
| `license`     | Yes      |           | Connect license file contents (GitHub secret)        |
| `version`     | No       | `release` | Connect version (e.g., `2024.08.0`, or `release`)   |
| `image`       | No       |           | Custom container image (overrides `version`)         |
| `config-file` | No       |           | Path to `rstudio-connect.gcfg` configuration file    |
| `port`        | No       | `3939`    | Port to map the container to                         |
| `quiet`       | No       | `false`   | Suppress progress indicators during image pull       |
| `env`         | No       |           | Environment variables for the Docker container       |
| `command`     | No       |           | Command to run (omit for start-only mode)            |
| `stop`        | No       |           | Container ID to stop                                 |

**Outputs (start-only mode):**

| Output            | Description                                      |
|-------------------|--------------------------------------------------|
| `CONNECT_API_KEY` | Admin API key for authentication                 |
| `CONNECT_SERVER`  | Connect server URL (e.g., `http://localhost:3939`)|
| `CONTAINER_ID`    | Docker container ID (for stopping later)         |

### Requirements

- Docker (available on GitHub Actions `ubuntu-latest` runners)
- A valid Posit Connect license file stored as a GitHub secret
- Minimum Connect version: 2022.10.0

### Proven usage pattern (from with-connect's own CI)

```yaml
- name: Start Connect
  id: connect
  uses: posit-dev/with-connect@main
  with:
    version: 2024.08.0
    license: ${{ secrets.CONNECT_LICENSE }}

- name: Use Connect
  run: |
    curl -f -H "Authorization: Key $CONNECT_API_KEY" \
      $CONNECT_SERVER/__api__/v1/content
  env:
    CONNECT_API_KEY: ${{ steps.connect.outputs.CONNECT_API_KEY }}
    CONNECT_SERVER: ${{ steps.connect.outputs.CONNECT_SERVER }}

- name: Stop Connect
  uses: posit-dev/with-connect@main
  with:
    stop: ${{ steps.connect.outputs.CONTAINER_ID }}
```

## What VIP tests can run in CI

### Tests that should work in Docker Connect

| Test file                          | Feasibility  | Notes                                              |
|------------------------------------|-------------|-----------------------------------------------------|
| `prerequisites/test_components`    | ✅ Yes       | Health endpoint check — straightforward             |
| `prerequisites/test_auth_configured` | ✅ Yes     | Checks env vars are set — config-level only         |
| `connect/test_auth` (API scenario) | ✅ Yes       | API key auth via `/__api__/v1/user`                 |
| `connect/test_auth` (UI scenario)  | ⚠️ Maybe    | Requires Playwright; Docker Connect uses password auth, but the bootstrapped user has no password set |
| `connect/test_content_deploy`      | ⚠️ Limited  | Needs R/Python runtimes installed in the container; Docker image may not include them by default |
| `connect/test_runtime_versions`    | ⚠️ Limited  | Depends on which runtimes are installed in the image |
| `connect/test_data_sources`        | ❌ No       | Requires external databases configured              |
| `connect/test_email`               | ❌ No       | Requires SMTP server configured                     |
| `connect/test_packages`            | ⚠️ Limited  | Depends on R/Python runtimes in the container       |

### Recommended initial test scope

Start with the tests that reliably work against a minimal Docker Connect
with no extra setup:

1. **`prerequisites/test_components`** — Connect health check
2. **`connect/test_auth` (API key scenario only)** — API authentication

These tests use only the API key provided by `with-connect` and don't
require runtimes, databases, or browser-based login. This gives us
confidence that VIP's core Connect testing path works end-to-end.

## Implementation plan

### Phase 1: Minimal smoke test workflow

Create a new workflow file `.github/workflows/connect-smoke.yml`:

```yaml
name: Connect Smoke Tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  connect-smoke:
    name: Smoke test against Connect
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Start Connect in Docker
      - name: Start Connect
        id: connect
        uses: posit-dev/with-connect@main
        with:
          version: "2024.08.0"
          license: ${{ secrets.CONNECT_LICENSE }}

      # Set up Python and install VIP
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync

      - name: Install Playwright browsers
        run: uv run playwright install chromium

      # Generate vip.toml from with-connect outputs
      - name: Configure VIP for CI Connect
        run: |
          cat > vip.toml << EOF
          [general]
          deployment_name = "CI Connect"

          [connect]
          enabled = true
          url = "${{ steps.connect.outputs.CONNECT_SERVER }}"
          api_key = "${{ steps.connect.outputs.CONNECT_API_KEY }}"

          [auth]
          provider = "password"
          EOF

      # Run the subset of tests that work against Docker Connect
      - name: Run Connect smoke tests
        run: |
          uv run pytest \
            tests/prerequisites/test_components.py \
            tests/connect/test_auth.py \
            -v -k "reachable or api" \
            --vip-config=vip.toml
        env:
          VIP_CONNECT_API_KEY: ${{ steps.connect.outputs.CONNECT_API_KEY }}

      # Stop Connect
      - name: Stop Connect
        if: always()
        uses: posit-dev/with-connect@main
        with:
          stop: ${{ steps.connect.outputs.CONTAINER_ID }}
```

**Key decisions:**

- **Single Connect version** to start (e.g., `2024.08.0`) — known
  stable, used in with-connect's own CI.
- **Generate `vip.toml` inline** from action outputs rather than
  committing a CI-specific config file.
- Use `-k "reachable or api"` to select only the scenarios that work
  without a browser-based login or runtimes.
- Use `if: always()` on the stop step so the container is cleaned up
  even if tests fail.

### Phase 2: Expand test coverage (future)

Once the minimal workflow is working, we can expand:

1. **Add a version matrix** to test against multiple Connect versions:
   ```yaml
   strategy:
     matrix:
       connect-version: ["2024.08.0", "release"]
   ```

2. **Enable Playwright UI tests** if Docker Connect supports password
   login for the bootstrapped admin user (needs investigation — the
   bootstrap endpoint creates a user with an API key but may not set a
   password).

3. **Test content deployment** by using a Connect Docker image that
   includes R and/or Python runtimes, or by passing environment
   variables to install them.

4. **Add test result upload** as a CI artifact for debugging failures:
   ```yaml
   - name: Upload test results
     if: always()
     uses: actions/upload-artifact@v4
     with:
       name: connect-smoke-results
       path: smoke-results.xml
   ```

### Phase 3: Version matrix and nightly runs (future)

- **Nightly schedule** to catch regressions against the latest Connect
  release without slowing down PR CI:
  ```yaml
  on:
    schedule:
      - cron: '0 6 * * *'  # daily at 6am UTC
  ```

- **Test against `release` (latest stable)** and a pinned older version
  to validate backward compatibility.

- **Test against `preview`** (nightly Connect builds) on a separate
  schedule to get early warning of breaking changes.

## Prerequisites for implementation

1. **GitHub secret**: A `CONNECT_LICENSE` secret containing a valid
   Posit Connect license file must be added to the `posit-dev/vip`
   repository (or organization) settings.

2. **Decide on trigger policy**: Should the smoke tests run on every PR,
   or only on pushes to `main` and a nightly schedule? Running on every
   PR provides the best signal but adds ~2-3 minutes to CI and uses
   Docker/license resources.

## Open questions

1. **License availability**: Is there an existing `CONNECT_LICENSE`
   secret available in the `posit-dev` organization, or does one need
   to be created for VIP specifically?

2. **Playwright in Docker Connect**: Does the bootstrapped admin user
   have a password that can be used for web UI login tests? If not, we
   may need to configure one via the Connect API or gcfg file.

3. **Runtime availability**: Do the standard Connect Docker images
   include R and Python runtimes? If not, content deployment tests
   will need a custom image or additional setup.

4. **CI cost/time budget**: How much additional CI time is acceptable
   for these smoke tests? Starting Connect in Docker typically takes
   30-60 seconds, plus test execution time.

5. **Version pinning strategy**: Should we pin to a specific Connect
   version, track `release`, or both?
