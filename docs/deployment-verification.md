# Deployment Verification

VIP can verify Posit Team deployments running in Kubernetes. The `vip verify`
command connects to a cluster, reads the Site custom resource, generates a
configuration, provisions credentials, and runs the test suite.

## Basic usage

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

## Cluster configuration

To use `vip verify`, add a `[cluster]` section to `vip.toml`:

```toml
[cluster]
provider = "aws"                     # "aws" or "azure"
name = "my-cluster-20260101"         # EKS/AKS cluster name
region = "us-east-1"                 # Cloud region
profile = "my-staging"              # AWS: profile name
role_arn = "arn:aws:iam::123:role/admin"  # AWS: cross-account role (optional)
```

### AWS EKS

- Requires `profile`, `region`, and cluster `name`
- Optional `role_arn` for cross-account access
- Uses boto3 to generate a kubeconfig with EKS token authentication

### Azure AKS

- Requires `subscription_id`, `resource_group`, and cluster `name`
- Uses Azure SDK to retrieve kubeconfig with managed identity auth

### Network access

VIP assumes the Kubernetes API is reachable (via Tailscale, VPN, or direct
access). If the `[cluster]` section is omitted, VIP uses the current
`KUBECONFIG`.

## Authentication modes

How credentials are provisioned depends on the deployment's auth provider:

| Deployment auth | Command | What happens |
|-----------------|---------|--------------|
| Keycloak | `vip verify <target>` | Test user auto-provisioned |
| Okta/OIDC | `vip verify <target> --interactive-auth` | Browser login + token minting |
| Pre-existing | `vip verify <target>` | Uses credentials from Secret or env vars |

Interactive auth requires the VIP CLI to be available in the Job container.
For Keycloak deployments, a test user is created automatically with a
cryptographically random password.
