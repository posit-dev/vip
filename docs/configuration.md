# Configuration

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

See `vip.toml.example` in the repository root for a fully commented template.
