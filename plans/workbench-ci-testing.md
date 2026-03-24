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

Unlike Connect, **there is no `posit-dev/with-workbench` action**.  We must
set up the Workbench container directly using Docker within the workflow.
Workbench is also a more complex product to start: it requires PAM user
accounts, a heavier runtime, and a different bootstrapping model.

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
| `workbench/test_ide_launch` | ❌ No | Requires R/Python; not in minimal image |
| `workbench/test_packages` | ❌ No | Requires R runtime |
| `workbench/test_data_sources` | ❌ No | Requires external databases |

> **Note:** `test_runtime_versions` and `test_sessions` were removed from the
> workbench test suite (commit `f45d242` on main). Runtime and session fixtures
> now live in `tests/workbench/conftest.py` and are consumed by `test_ide_launch`.

### Recommended initial test scope

1. **`prerequisites/test_components`** — Workbench health check (no credentials)
2. **`workbench/test_auth`** — Web UI login with the PAM test user

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

### Phase 1: Minimal smoke test workflow

Create `.github/workflows/workbench-smoke.yml`:

```yaml
name: Workbench Smoke Tests

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: "0 7 * * *"  # daily at 7am UTC (offset from Connect run at 6am)

permissions:
  contents: read
  checks: write

jobs:
  workbench-smoke:
    name: Smoke test against Workbench ${{ matrix.workbench-version }}
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        workbench-version: ${{ github.event_name == 'schedule' && fromJSON('["ubuntu2204-2026.01.1", "ubuntu2204"]') || fromJSON('["ubuntu2204-2026.01.1"]') }}
    steps:
      - uses: actions/checkout@v4

      # Start Workbench in Docker
      - name: Start Workbench
        run: |
          docker run -d \
            --name workbench \
            -p 8787:8787 \
            -e RSP_LICENSE="${{ secrets.WORKBENCH_LICENSE }}" \
            rstudio/rstudio-workbench:${{ matrix.workbench-version }}
      - name: Create test user
        run: |
          timeout 180 bash -c '
            until docker exec workbench sh -c "true" 2>/dev/null; do sleep 3; done
          '
          docker exec workbench useradd -m -s /bin/bash rstudio
          docker exec workbench sh -c "echo 'rstudio:rstudio' | chpasswd"

      # Wait for the server to be ready
      - name: Wait for Workbench to be ready
        run: |
          timeout 180 bash -c \
            'until curl -sf http://localhost:8787/health-check; do sleep 5; done'

      # Resolve the actual Workbench version
      - name: Resolve Workbench version
        id: version
        run: |
          VERSION=$(curl -sf http://localhost:8787/api/server-info | jq -r '.version')
          if [ -z "${VERSION}" ] || [ "${VERSION}" = "null" ]; then
            echo "ERROR: Could not resolve Workbench version"
            exit 1
          fi
          echo "Resolved Workbench version: ${VERSION}"
          echo "resolved=${VERSION}" >> "$GITHUB_OUTPUT"

      # Rename the check run to show the resolved version
      - name: Update job title with resolved version
        uses: actions/github-script@v7
        with:
          script: |
            const resolvedVersion = '${{ steps.version.outputs.resolved }}';
            const { data: { jobs } } = await github.rest.actions.listJobsForWorkflowRun({
              owner: context.repo.owner,
              repo: context.repo.repo,
              run_id: context.runId,
            });
            const currentJob = jobs.find(
              j => j.status === 'in_progress' && j.name.includes('${{ matrix.workbench-version }}')
            );
            if (currentJob) {
              await github.rest.checks.update({
                owner: context.repo.owner,
                repo: context.repo.repo,
                check_run_id: currentJob.id,
                name: `Smoke test against Workbench ${resolvedVersion}`,
              });
            }

      # Set up Python and install VIP
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync

      - name: Install Playwright browsers
        run: uv run playwright install chromium

      # Generate vip.toml from Docker outputs
      - name: Configure VIP for CI Workbench
        run: |
          cat > vip.toml << EOF
          [general]
          deployment_name = "CI Workbench"

          [workbench]
          enabled = true
          url = "http://localhost:8787"
          version = "${{ steps.version.outputs.resolved }}"

          [auth]
          provider = "password"
          username = "rstudio"
          password = "rstudio"
          EOF

      # Run the subset of tests that work against Docker Workbench
      - name: Run Workbench smoke tests
        run: |
          uv run pytest \
            tests/prerequisites/test_components.py \
            tests/workbench/test_auth.py \
            -v -k "workbench" \
            --vip-config=vip.toml \
            --junitxml=smoke-results.xml

      # Upload test results for debugging
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: workbench-smoke-results-${{ steps.version.outputs.resolved }}
          path: smoke-results.xml

      # Write a rich job summary
      - name: Write workflow summary
        if: always()
        run: |
          RESOLVED="${{ steps.version.outputs.resolved }}"
          WB_URL="http://localhost:8787"
          REQUESTED="${{ matrix.workbench-version }}"
          RUN_DATE=$(date -u '+%Y-%m-%d %H:%M UTC')
          {
            echo "## 🧪 Workbench Smoke Tests — v${RESOLVED}"
            echo ""
            echo "| | |"
            echo "|---|---|"
            echo "| 🏷️ **Requested version** | \`${REQUESTED}\` |"
            echo "| ✅ **Resolved version** | \`${RESOLVED}\` |"
            echo "| 🌐 **Workbench URL** | \`${WB_URL}\` |"
            echo "| 📅 **Run date** | ${RUN_DATE} |"
            echo ""
          } >> "$GITHUB_STEP_SUMMARY"
          if [ -f smoke-results.xml ]; then
            TESTS=$(grep -oP '(?<=tests=")[^"]+' smoke-results.xml | head -1 || echo 0)
            FAILURES=$(grep -oP '(?<=failures=")[^"]+' smoke-results.xml | head -1 || echo 0)
            ERRORS=$(grep -oP '(?<=errors=")[^"]+' smoke-results.xml | head -1 || echo 0)
            SKIPPED=$(grep -oP '(?<=skipped=")[^"]+' smoke-results.xml | head -1 || echo 0)
            TESTS=${TESTS:-0}; FAILURES=${FAILURES:-0}; ERRORS=${ERRORS:-0}; SKIPPED=${SKIPPED:-0}
            PASSED=$(( TESTS - FAILURES - ERRORS - SKIPPED ))
            {
              echo "### 📊 Test Results"
              echo ""
              echo "| Result | Count |"
              echo "|--------|-------|"
              echo "| ✅ Passed | ${PASSED} |"
              echo "| ❌ Failed | ${FAILURES:-0} |"
              echo "| ⚠️ Errors | ${ERRORS:-0} |"
              echo "| ⏭️ Skipped | ${SKIPPED:-0} |"
              echo "| 📝 **Total** | **${TESTS:-0}** |"
              echo ""
              if [ "${FAILURES:-0}" = "0" ] && [ "${ERRORS:-0}" = "0" ]; then
                echo "🎉 **All tests passed!**"
              else
                echo "💥 **Some tests failed — check the logs for details.**"
              fi
            } >> "$GITHUB_STEP_SUMMARY"
          else
            echo "> ⚠️ Test results file not found — tests may have been skipped." >> "$GITHUB_STEP_SUMMARY"
          fi

      # Stop and remove Workbench container
      - name: Stop Workbench
        if: always()
        run: docker stop workbench && docker rm workbench || true
```

**Key decisions:**

- **No `with-workbench` action**: Docker is used directly since no equivalent
  action exists yet.
- **PAM user creation**: A test user `rstudio`/`rstudio` is created with
  `useradd` + `chpasswd` inside the container.
- **Single version on PRs**: Only `ubuntu2204-2026.01.1` is tested on push/PR
  to keep CI fast.  The `ubuntu2204` (latest) tag is added on scheduled runs
  to catch regressions.
- **Offline schedule offset**: The cron runs at 7am UTC, one hour after the
  Connect smoke run (6am), to avoid resource contention.
- **Generous timeouts**: 180 seconds for container readiness, vs. 60–120 for
  Connect, because Workbench takes longer to boot.
- **Cleanup with `if: always()`**: Container is removed even when tests fail.

### Phase 2: Expand test coverage (future)

Once Phase 1 is stable:

1. **Add a version matrix** for additional stable releases.
2. **Add `workbench/test_ide_launch`** using a Workbench image that ships
   R/Python runtimes, or build a custom image on top of the official one.
   The `wb_start_session` fixture in `tests/workbench/conftest.py` already
   provides the session-launch helper.
3. **Add `workbench/test_packages`** once R runtime is available in the image.

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

3. **UI selector accuracy**: The Playwright selectors in `test_auth.py` use the
   page-object classes in `tests/workbench/pages/` — mirroring the rstudio-pro
   e2e selectors (`#posit-logo`, `#current-user`, etc.).  They should be accurate
   for the 2026.01 image but may need adjustment for older releases.

4. **Session support**: The Workbench Docker image includes two versions of R
   and two versions of Python (per Docker Hub docs), so IDE launch tests should
   work once Phase 2 is implemented.

5. **`/api/server-info` authentication**: The Workbench `/api/server-info` endpoint
   requires authentication. Version resolution uses `POST /auth-sign-in` to get a
   session cookie, then `GET /api/server-info` with that cookie.  This also
   validates that password auth is working before the Playwright tests run.
