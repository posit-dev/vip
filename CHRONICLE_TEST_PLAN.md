# Chronicle test — live validation plan (fuzzbucket)

Working/scratch doc (not for commit). Goal: validate the `feat/chronicle-tests`
branch against a real Workbench with Chronicle enabled.

## 1. Current branch state

- Repo: `~/git/vip`, branch `feat/chronicle-tests`, rebased on `origin/main`
  (0.52.0), **1 commit ahead / 0 behind**, tree clean. Commit `cbca9340`.
- Local selftests pass (`uv run pytest selftests/ -q` → 891 passed), ruff clean.
- Run vip from this checkout with `uv run vip ...` (uv is at `~/.local/bin/uv`;
  `uvx`/`ruff`/`just` are not on PATH in bare shells — use `~/.local/bin/uv run ...`
  or `~/.local/bin/uv tool run ruff@0.15.0 ...`).

## 2. What the test does

One `@workbench` scenario in `src/vip_tests/workbench/test_chronicle.py` +
`.feature`. It logs into Workbench (Playwright), launches an RStudio session,
joins it, and runs an in-session R probe via the **chronicle.reports** package
(github.com/posit-dev/chronicle-reports) to confirm Chronicle wrote queryable
Parquet data. Chronicle has **no query API** — reading the data back in-session
is the only way to prove collection.

It asserts all **three** collection paths, each via the raw metric it produces
(verified against the chronicle source):

| Path | Raw metric | Source / receiver | Server config to enable |
|------|-----------|-------------------|-------------------------|
| 1. Runtime metrics | `pwb_sessions_launched_total` | Prometheus scrape | works once Chronicle enabled |
| 2. Session events | `pwb_sessions` | OTLP logs (`convertPWBSession(logs)`) | `otel-*` + `LogOTLPEndpoint` + **Monitoring license** |
| 3. User information | `pwb_users` | `workbenchapi` receiver | `workbench-api-admin-enabled=1` |

Probe tokens → behavior:
- `VIP_NO_PKG` → **skip** whole scenario (chronicle.reports not installed; it's
  the verification mechanism, not the SUT).
- `VIP_NO_DATA` (per path) → **fail** with a message naming the exact config +
  the read-permission caveat.
- `VIP_DATA_OK` → pass.

Config (in `src/vip/config.py`, `WorkbenchConfig`):
- `chronicle_enabled: bool = False` — gate; scenario skips unless `true`.
- `chronicle_data_path: str = "/var/lib/rstudio-server/shared-storage/chronicle"`
  — base_path passed to chronicle.reports.

## 3. OPEN DECISION (resolve before/with merge)

The rebase surfaced a naming overlap. Upstream PR #393 added a **Connect**
Chronicle test using a **top-level `[chronicle] enabled`** →
`VIPConfig.chronicle_enabled` (consumed by a `chronicle_enabled` fixture in
`src/vip_tests/conftest.py`). Mine uses **`[workbench] chronicle_enabled` +
`[workbench] chronicle_data_path`**. They don't technically collide (different
attributes) but it's confusing. Decide: keep per-product (mine is Workbench-
specific and needs a data path; Connect's is an API check) vs. unify. Lightweight
either way; just make it deliberate.

## 4. Testing tiers

- **Tier 1b (plumbing, no Chronicle needed):** point vip at a plain box with
  `chronicle_enabled=true` and chronicle.reports NOT installed → test logs in,
  launches session, runs probe, **skips on `VIP_NO_PKG`**. Proves the whole
  Playwright + in-session R pipeline works. This is the minimum "does it work".
- **Tier 2 (full green):** Chronicle fully configured + chronicle.reports
  installed + data accumulated → all three assertions **pass**. Requires the
  Monitoring license for path 2 (OTLP).

We chose Workbench version **`2026.06.0+242.pro13`** because it bundles the
`posit-chronicle` binary (required — Workbench won't boot with
`chronicle-enabled=1` if the binary/`metrics-enabled=1` are missing).

## 5. Prerequisites status (checked 2026-07-07)

Present: `fuzzbucket-client` (`~/.local/bin`), `pwbauthpwd`
(`~/git/rstudio-ide-automation/pwbauthpwd`), `greadlink` (`/opt/local/bin`),
`op` (1Password CLI), `deployIDE.sh`.


## 6. Step-by-step

### A. Deploy the box (provisions real EC2, ~4h TTL; costs money)
```bash
cd ~/git/rstudio-ide-automation/fuzzbucket
# ensure FUZZBUCKET_URL set, logged in, op signed in, gnu readlink on PATH
./deployIDE.sh -c ubuntu22 -a -v 2026.06.0+242.pro13 -t 14400
cat environment_maps/environment_map.ubuntu22.json   # -> hostname / public_ip
# SSH pattern (see fuzz_ssh in deployIDE.sh): login user is `ubuntu` for ubuntu22
fuzzbucket-client ssh ubuntu22
```
Notes: SSL is ON by default (self-signed test CA) → vip must use `insecure=true`.
Workbench at `https://<hostname>/` (443), rserver also 8787. Health:
`https://<hostname>/health-check`.

### B. Enable Chronicle on the box (SSH in, sudo)
Append to `/etc/rstudio/rserver.conf`:
```ini
metrics-enabled=1
chronicle-enabled=1
workbench-api-admin-enabled=1
otel-enabled=1
otel-logs-enabled=1
otel-logs-endpoint=http://localhost:5959/v1/logs
```
Create `/etc/rstudio/chronicle-local.gcfg`:
```ini
[Workbench]
LogOTLPEndpoint = localhost:5959
[LocalStorage]
Access = all
```
Then `sudo rstudio-server restart`. Verify:
```bash
pgrep -x posit-chronicle                       # single PID
sudo stat -c '%a' /var/lib/rstudio-server/chronicle.gcfg   # 640
grep -i Location /var/lib/rstudio-server/chronicle.gcfg     # confirm data path
```
IMPORTANT: confirm the data path matches vip's `chronicle_data_path`. Read the
generated `chronicle.gcfg` `[LocalStorage] Location` (derives from
`server-shared-storage-path`); if it isn't
`/var/lib/rstudio-server/shared-storage/chronicle`, set `chronicle_data_path`
in the vip.toml (step D) to match.
Path 2 (OTLP) needs the **Monitoring license feature** — if the fuzzbucket
license lacks it, path 2 will legitimately have no data (expect that assertion
to fail; paths 1 and 3 should still pass).

### C. Install chronicle.reports in the session R library (SSH in)
```bash
# system lib so the session user can load it; use the R that sessions use
sudo R -e 'install.packages("pak", repos="https://packagemanager.posit.co/cran/latest"); pak::pak("posit-dev/chronicle-reports")'
```
(Verify in a session later with `requireNamespace("chronicle.reports")`.)

### D. Generate data
Chronicle collects runtime metrics immediately, but user info comes from the
Workbench API scrape (default interval ~20m) and session events after a session
ends + OTLP flush. So: log in once, **launch and then quit an RStudio session**,
and wait ~20–30 min before expecting all three paths to have rows. (The vip test
itself launches a session, but a single fresh run may predate the first scrape.)

### E. Run vip against the box
```bash
cd ~/git/vip
cat > /tmp/vip-fuzz.toml <<'EOF'
[workbench]
enabled = true
url = "https://<hostname>/"
chronicle_enabled = true
# chronicle_data_path = "..."   # only if step B showed a non-default Location
[connect]
enabled = false
[package_manager]
enabled = false
[auth]
provider = "password"
username = "zach"                 # a pwbauthpwd IDE-team user (or admin/.RStudio.001)
password = "<contents of ~/git/rstudio-ide-automation/pwbauthpwd>"
[tls]
insecure = true
EOF
uv run vip verify --config /tmp/vip-fuzz.toml -f test_chronicle_collects_data -- -v
```

### Expected results
- Chronicle NOT enabled / chronicle.reports missing → **skip** (`VIP_NO_PKG`) —
  proves plumbing (Tier 1b).
- Fully configured + data present → **pass** (Tier 2). If Monitoring license is
  absent, path 2 (session events) fails while paths 1 & 3 pass.

### F. Teardown
```bash
cd ~/git/rstudio-ide-automation/fuzzbucket && ./deployIDE.sh -d ubuntu22
```

## 7. Handy references
- Chronicle admin doc: `~/git/rstudio-pro/docs/server/admin/auditing_and_monitoring/chronicle.qmd`
- chronicle gcfg options / Access levels: chronicle repo `internal/config/access.go`,
  `internal/config/config.go` (`[LocalStorage] Access` = all|group|owner).
- Full Chronicle env (alternative to hand-config): Pulumi `dogfood` stack —
  `~/git/rstudio-pro/pulumi/eks-reference/README-dogfood.md`.
- Demo of the branch: `validation_docs/demo-chronicle-tests.md`.
