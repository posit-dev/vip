# VIP - Verified Installation of Posit

![VIP mascot](https://github.com/user-attachments/assets/f28c5cb5-701a-4491-99f9-102ff6fb6283)

An open-source, extensible test suite that validates Posit Team deployments are
installed correctly and functioning properly.

VIP uses **BDD-style tests** (pytest-bdd + Playwright) to verify Connect,
Workbench, and Package Manager.  Results are compiled into a **Quarto report**
that can be published to a Connect server.

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip
- **[just](https://just.systems/)** (optional, for running common tasks)

## Quick start

```bash
# Clone the repo
git clone https://github.com/posit-dev/vip.git
cd vip

# Set up with uv (recommended)
uv sync                          # install all dependencies
uv run playwright install chromium

# Or set up with pip
pip install -e ".[dev]"
playwright install chromium

# Configure
cp vip.toml.example vip.toml
# Edit vip.toml with your deployment details

# Set secrets via environment variables
export VIP_CONNECT_API_KEY="your-api-key"
export VIP_TEST_USERNAME="test-user"
export VIP_TEST_PASSWORD="test-password"

# Run all tests
uv run pytest              # with uv
pytest                     # with pip

# Run tests for a single product
uv run pytest -m connect
uv run pytest -m workbench
uv run pytest -m package_manager

# Generate the Quarto report
uv run pytest --vip-report=report/results.json
cd report && quarto render
```

## Configuration

Copy `vip.toml.example` to `vip.toml` and edit it for your deployment.  Each
product section can be disabled individually by setting `enabled = false`.

Secrets (API keys, passwords) should be set via environment variables rather
than stored in the configuration file:

| Variable | Purpose |
|---|---|
| `VIP_CONNECT_API_KEY` | Connect admin API key |
| `VIP_WORKBENCH_API_KEY` | Workbench admin API key |
| `VIP_PM_TOKEN` | Package Manager token |
| `VIP_TEST_USERNAME` | Test user login name |
| `VIP_TEST_PASSWORD` | Test user login password |
| `VIP_CLUSTER_PROVIDER` | Cloud provider (`aws` or `azure`) |
| `VIP_CLUSTER_NAME` | EKS/AKS cluster name |
| `VIP_CLUSTER_REGION` | Cloud region |
| `VIP_AWS_PROFILE` | AWS profile name |
| `VIP_AWS_ROLE_ARN` | IAM role for cross-account access |

You can also point to the config file explicitly:

```bash
pytest --vip-config=/path/to/vip.toml
```

## Authentication

VIP tests that verify login flows and authenticated functionality need user
credentials.  How you provide them depends on the deployment's identity
provider.

### Password / LDAP / Keycloak (headless)

Set credentials via environment variables and run normally:

```bash
export VIP_TEST_USERNAME="test-user"
export VIP_TEST_PASSWORD="test-password"
uv run pytest
```

For deployments with Keycloak, `vip verify` handles this automatically —
it provisions a test user and passes credentials to VIP.

### Okta / external OIDC provider (interactive)

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

### Cluster connection

VIP can connect to Kubernetes clusters to run tests or manage credentials:

```bash
# Connect to a cluster (standalone, for debugging)
vip cluster connect my-target
```

The cluster configuration comes from the `[cluster]` section in `vip.toml` or
can be overridden via CLI flags. See the Configuration section below for
details.

## Deployment verification

VIP can verify Posit Team deployments running in Kubernetes. The `vip verify`
command connects to a cluster, reads the Site custom resource, generates a
configuration, provisions credentials, and runs the test suite.

### Basic usage

```bash
# Connect to cluster and run all tests as a K8s Job
vip verify ganso01-staging

# Use interactive auth for OIDC deployments
vip verify ganso01-staging --interactive-auth

# Run locally instead of K8s Job
vip verify ganso01-staging --local

# Just generate and print the vip.toml config
vip verify ganso01-staging --config-only

# Run specific test categories
vip verify ganso01-staging --categories prerequisites

# Clean up test credentials
vip verify cleanup ganso01-staging
```

### Cluster configuration

To use `vip verify`, add a `[cluster]` section to `vip.toml`:

```toml
[cluster]
provider = "aws"                     # "aws" or "azure"
name = "my-cluster-20260101"         # EKS/AKS cluster name
region = "us-east-1"                 # Cloud region
profile = "my-staging"              # AWS: profile name
role_arn = "arn:aws:iam::123:role/admin"  # AWS: cross-account role (optional)
```

**AWS EKS:**
- Requires `profile`, `region`, and cluster `name`
- Optional `role_arn` for cross-account access
- Uses boto3 to generate a kubeconfig with EKS token authentication

**Azure AKS:**
- Requires `subscription_id`, `resource_group`, and cluster `name`
- Uses Azure SDK to retrieve kubeconfig with managed identity auth

**Network access:**
VIP assumes the Kubernetes API is reachable (via Tailscale, VPN, or direct
access). If the `[cluster]` section is omitted, VIP uses the current
`KUBECONFIG`.

### Authentication modes for verify

How credentials are provisioned depends on the deployment's auth provider:

| Deployment auth | Command | What happens |
|-----------------|---------|--------------|
| Keycloak | `vip verify <target>` | Test user auto-provisioned |
| Okta/OIDC | `vip verify <target> --interactive-auth` | Browser login + token minting |
| Pre-existing | `vip verify <target>` | Uses credentials from Secret or env vars |

Interactive auth requires the VIP CLI to be available in the Job container.
For Keycloak deployments, a test user is created automatically with a
cryptographically random password.

## Test categories

| Category | Marker | Description |
|---|---|---|
| Prerequisites | `prerequisites` | Components installed, auth configured, admins onboarded |
| Package Manager | `package_manager` | CRAN/PyPI mirrors, repos, private packages |
| Connect | `connect` | Login, content deploy, data sources, packages, email, runtimes |
| Workbench | `workbench` | Login, IDE launch, sessions, packages, data sources, runtimes |
| Cross-product | `cross_product` | SSL, monitoring, system resources |
| Performance | `performance` | Load times, package install speed, concurrency, resource usage |
| Security | `security` | HTTPS enforcement, auth policy, secrets storage |

Run a specific category:

```bash
pytest -m connect
pytest -m "performance and connect"
```

## Version support

Tests can be pinned to product versions with the `min_version` marker:

```python
@pytest.mark.min_version(product="connect", version="2024.05.0")
def test_new_api_feature():
    ...
```

Tests that target a version newer than the deployment under test are
automatically skipped.

## Extensibility

Customers can add site-specific tests without modifying the VIP source tree.

1. Create a directory with `.feature` and `.py` files following the same
   conventions as the built-in tests.
2. Point VIP at it via configuration or the CLI:

```toml
# vip.toml
[general]
extension_dirs = ["/opt/vip-custom-tests"]
```

```bash
pytest --vip-extensions=/opt/vip-custom-tests
```

The custom tests directory is added to pytest's collection path at runtime.
See `examples/custom_tests/` for a working example.

## Quarto report

After running the tests, generate a report:

```bash
pytest --vip-report=report/results.json
cd report
quarto render
```

The rendered report can be published to Connect:

```bash
quarto publish connect --server https://connect.example.com
```

## Design principles

- **Non-destructive** - tests create, verify, and clean up their own content.
  They never modify or delete existing customer content.
- **Diagnostic** - tests are sequenced so failures localize problems.
  Prerequisites run first; product tests follow.
- **Loosely coupled** - the suite avoids tight coupling to product client
  libraries.  API calls use plain HTTP where practical.
- **Duplication over coupling** - code duplication with product-internal test
  suites is acceptable if it keeps VIP independent and version-flexible.

## Development

### Setup

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies (including dev tools like ruff)
uv sync

# Or with pip
pip install -e ".[dev]"
```

### Linting and formatting

VIP uses [ruff](https://docs.astral.sh/ruff/) for both linting and code
formatting.  The easiest way to run checks is with [just](https://just.systems/):

```bash
just check          # run both lint and format checks
just fix            # auto-fix lint issues and reformat

# Or individually
just lint           # ruff check
just format-check   # ruff format --check
just lint-fix       # ruff check --fix
just format         # ruff format
```

Without just, run ruff directly:

```bash
uv run ruff check src/ tests/        # lint
uv run ruff format --check src/ tests/  # format check
uv run ruff check --fix src/ tests/  # auto-fix lint
uv run ruff format src/ tests/       # reformat
```

### Type checking

```bash
uv run mypy src/
```

## License

MIT - see [LICENSE](LICENSE).
