# Design — #411: Remove Shiny and Kubernetes modes

**Status:** Approved design (brainstorming) — ready for implementation plan
**Date:** 2026-06-30
**Issue:** posit-dev/vip#411
**Dispatch order:** FIRST (independent; unblocks #409)

## Decision

Hard-delete both the Shiny app mode and the Kubernetes execution mode in a single PR.
VIP becomes a purely local CLI: the user supplies a `vip.toml` (or `--connect-url` /
`--workbench-url` / `--pm-url` flags) and runs tests against reachable product URLs.
Pre-1.0, so no deprecation period.

Rationale (from issue + meeting): the team has converged on the CLI experience. These
modes are not out of scope for the future, but are not a 1.0 priority and carry
maintenance + dependency-surface cost.

## Scope — remove

### Kubernetes mode (remove the entire `--k8s` chain)
- `Mode.k8s_job` and `Mode.config_only` in `src/vip/config.py` — collapse the `Mode`
  enum to `local` only, or remove mode-branching entirely if `local` becomes implicit.
- `--k8s` and `--config-only` CLI flags and the `cluster connect` subcommand in
  `src/vip/cli.py`.
- `src/vip/cluster/` — `aws.py`, `azure.py`, `kubeconfig.py`, `target.py`.
- `src/vip/verify/` — `site.py` (Site CR parsing), `credentials.py` (Keycloak/interactive
  cred provisioning), `job.py` (K8s Job submission + log streaming).
- The `_run_k8s_job` / `_phase_provision_credentials` code paths in `cli.py`, and the
  `cleanup_credentials` branch in the `cleanup` command (`cli.py:~1097`).

### Shiny mode (the `vip app` graphical runner — NOT the Shiny product tests)
- `app` subcommand + `run_app` in `cli.py`; the entire `src/vip/app/` directory.
- `shiny[theme]` from core `dependencies` in `pyproject.toml`, plus the
  `python-multipart` and `starlette` pins that exist ONLY as shiny transitives
  (confirm during impl they are not required by anything else).
- Shiny-only code in `src/vip/report_html.py` — keep whatever the Quarto report needs.

## Scope — keep (explicit, to prevent over-deletion)
- Subcommands: `verify`, `cleanup`, `install`, `uninstall`, `report`, `status`,
  `scaffold`, `auth mint-connect-key`.
- CLI-flag config generation (`vip verify --connect-url URL` etc.) — independent of K8s.
- `run_status` (preflight health checks) — verified NOT K8s-coupled.
- **All Shiny *product tests*** (deploying Shiny apps to Connect, Python Shiny bundles in
  `src/vip_tests/`) — these exercise the product, unrelated to "Shiny mode".

## Cross-issue dependency (IMPORTANT)
- **Do NOT delete the root `Dockerfile`.** Its header says "for Kubernetes Jobs" and
  `verify/job.py` was its consumer, but the image itself is a generic
  "install VIP + Playwright, ENTRYPOINT pytest" runner. #409 will **repurpose** it as the
  CI runner image for containerized integration + mock-IdP E2E. Update its comment to
  drop the K8s framing; leave the image otherwise intact.
- The `docker/` subdirectory images (connect, workbench, packagemanager, rhel9/10,
  opensuse-leap) are separate product/platform smoke images — leave untouched.

## Verification confirmed during design
- `auth.py` / `idp.py` import none of `cluster/` or `verify/` → `--interactive-auth` /
  `--headless-auth` are independent of K8s mode. Removing K8s does not touch #409's subject.
- `verify/credentials.py` is imported only by the K8s workflow in `cli.py`.

## Acceptance criteria
- Selftests pass (`uv run pytest selftests/ -v`).
- `vip --help` shows no `app` or `cluster` subcommands; no `--k8s` / `--config-only` flags.
- `uv run ruff check` + `uv run ruff format --check` + `uv run mypy src/vip/` all clean.
- No dangling imports or dead references to removed modules.
- Docs updated/removed: `README.md`, `docs/shiny-app.md` (delete), `CLAUDE.md` (drop K8s
  + Shiny-mode references in the file table and prose), any K8s-mode docs.
- `pyproject.toml` no longer depends on `shiny` (and orphaned transitive pins removed).
- Showboat demo proving the slimmed CLI still verifies products end-to-end.
