# Feature: Remove Shiny and Kubernetes modes

*2026-07-01T17:29:36Z by Showboat 0.6.1*
<!-- showboat-id: f716ce52-3a5e-41f9-a2fc-7e381771d17e -->

Issue #411 removes the `vip app` Shiny runner and the `--k8s` Kubernetes execution mode, making VIP a purely local CLI ahead of 1.0. Below: the slimmed CLI surface (no app/cluster commands), clean lint, and passing CLI/config selftests.

```bash
uv run vip --help
```

```output
usage: vip [-h]
           {auth,verify,cleanup,install,uninstall,report,status,scaffold} ...

VIP verification and credential tools

positional arguments:
  {auth,verify,cleanup,install,uninstall,report,status,scaffold}
    auth                Authentication tools
    verify              Run VIP tests against a Posit Team deployment
    cleanup             Delete VIP test credentials and resources
    install             Install system packages and Playwright Chromium
    uninstall           Reverse vip install (dry-run by default; --yes to
                        execute)
    report              Render the Quarto report from a results.json file
    status              Check health endpoints for each configured product
    scaffold            Generate a ready-to-run custom test extension
                        directory

options:
  -h, --help            show this help message and exit
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run pytest selftests/test_cli_verify.py selftests/test_config.py -q 2>&1 | grep -E 'passed|failed' | sed 's/ in [0-9.]*s//'
```

```output
191 passed, 1 warning
```
