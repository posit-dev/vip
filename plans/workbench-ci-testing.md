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
| `RSP_LICENSE` | License activation key (required) |

### Health check and version endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health-check` | Returns `200 OK` when the server is ready |
| `GET /api/server-info` | Returns JSON with `version`, `mode`, etc. |

### User setup

Workbench uses PAM authentication by default in Docker.  Users must exist in
the container's OS.  A test user can be created with standard Linux tools:

```bash
docker exec workbench useradd -m -s /bin/bash rstudio
docker exec workbench sh -c "echo 'rstudio:rstudio' | chpasswd"
```

### Startup time

Workbench takes longer to start than Connect — typically **60–180 seconds** on
a GitHub Actions `ubuntu-latest` runner.  The workflow must poll the health
endpoint with a generous timeout.

### Proven usage pattern

```bash
# Start container
docker run -d \
  --name workbench \
  -p 8787:8787 \
  -e RSP_LICENSE="${LICENSE_KEY}" \
  rstudio/rstudio-workbench:ubuntu2204-2026.01.1

# Wait for ready
timeout 180 bash -c 'until curl -sf http://localhost:8787/health-check; do sleep 5; done'

# Resolve version
VERSION=$(curl -sf http://localhost:8787/api/server-info | jq -r '.version')

# Run tests
pytest tests/prerequisites/test_components.py tests/workbench/test_auth.py ...

# Cleanup
docker stop workbench && docker rm workbench || true
```

## What VIP tests can run in Docker Workbench

| Test file | Feasibility | Notes |
|---|---|---|
| `prerequisites/test_components` | ✅ Yes | Health-check only — no auth required |
| `workbench/test_auth` | ✅ Yes | Web UI login with PAM user created in container |
| `workbench/test_runtime_versions` | ❌ No | No R/Python runtimes in the minimal image |
| `workbench/test_sessions` | ❌ No | Requires runtimes; session launch fails without them |
| `workbench/test_ide_launch` | ❌ No | Requires R/Python; not in minimal image |
| `workbench/test_packages` | ❌ No | Requires R runtime |
| `workbench/test_data_sources` | ❌ No | Requires external databases |

### Recommended initial test scope

1. **`prerequisites/test_components`** — Workbench health check (no credentials)
2. **`workbench/test_auth`** — Web UI login with the PAM test user

These cover the core "is Workbench up and can a user log in?" path with no
external dependencies.

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
2. **Add `workbench/test_sessions`** using a Workbench image that ships
   R/Python runtimes, or build a custom image on top of the official one.
3. **Add `workbench/test_runtime_versions`** once runtimes are available.
4. **Add `workbench/test_ide_launch`** to verify RStudio, VS Code, and
   JupyterLab launch correctly.

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

1. **License format**: Is the Workbench license available as a plain activation
   key string (for `RSP_LICENSE`) or only as a file?  If only a file, the
   workflow must write the secret to disk before mounting it.

2. **Image availability**: Are all required version tags available on Docker
   Hub for `rstudio/rstudio-workbench`?  Some older versions may only exist in
   a private registry.

3. **UI selector accuracy**: The Playwright selectors in `test_auth.py`
   (`#username`, `#password`, `button[type='submit']`) were written without
   running against the real Workbench UI.  They may need adjustment once
   tested against a live Docker container.

4. **Session support**: The minimal Workbench Docker image may not include R
   or Python runtimes.  Session-based tests will fail unless a custom image
   or additional setup installs them.

5. **`/api/server-info` format**: The JSON key for the version string in
   `/api/server-info` needs to be verified against a running instance (assumed
   to be `version` based on the Workbench client code in `src/vip/clients/workbench.py`).
