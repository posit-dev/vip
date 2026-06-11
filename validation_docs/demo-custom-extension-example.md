# feat(examples): add custom test extension example and vip scaffold (closes #298)

*2026-06-11T18:20:12Z by Showboat 0.6.1*
<!-- showboat-id: 94a56b1b-51f2-4ad3-9e74-7749b60bd31a -->

This PR adds two things to VIP:

1. A new `vip scaffold` CLI subcommand that copies a reference cross-product validation
   example to a user-specified directory.
2. The reference example itself at `examples/cross_product_validation/`, which verifies
   R/Python runtime versions and DESeq2/PyDeSEQ2 package installability across Connect
   and Workbench — the pattern GxP deployments and other regulated environments need.

Selftests at `selftests/test_cli_scaffold.py` verify the scaffold command output.

```bash
uv run vip --help 2>&1 | grep -E 'scaffold|verify'
```

```output
           {auth,verify,cleanup,install,uninstall,cluster,report,status,scaffold,app}
  {auth,verify,cleanup,install,uninstall,cluster,report,status,scaffold,app}
    verify              Run VIP tests against a Posit Team deployment
    scaffold            Generate a ready-to-run custom test extension
```

```bash
uv run vip scaffold --help
```

```output
usage: vip scaffold [-h] [--output DIR] [--force]

Copy the cross_product_validation example to a new directory, ready to
customise and run with:

  vip verify --config vip.toml --extensions <output-dir>

The example verifies specific R/Python runtime versions and package
installability across Workbench and Connect. Edit the generated
conftest.py to set your own package names and version requirements.

See vip.toml.example for the [runtimes] block you need to populate.

options:
  -h, --help    show this help message and exit
  --output DIR  Destination directory for the scaffolded extension (default:
                ./custom_tests)
  --force       Overwrite destination if it already exists
```

```bash
uv run vip scaffold --output /tmp/claude/scaffold-demo --force && ls /tmp/claude/scaffold-demo
```

```output
Scaffolded extension to: /tmp/claude/scaffold-demo

Next steps:
  1. Edit /tmp/claude/scaffold-demo/conftest.py to set your package names and versions.
  2. Add a [runtimes] block to vip.toml:
       [runtimes]
       r_versions = ["4.4.0"]
       python_versions = ["3.11.0"]
  3. Run the extension:
       vip verify --config vip.toml --extensions /tmp/claude/scaffold-demo

See /tmp/claude/scaffold-demo/README.md for full customization instructions.
conftest.py
README.md
test_gxp_validation.feature
test_gxp_validation.py
```

```bash
uv run pytest --vip-config=/tmp/claude/vip-test.toml --vip-extensions=/tmp/claude/scaffold-demo --collect-only -q 2>&1 | grep -E 'test_gxp|collected'
```

```output
test_gxp_validation.py::test_connect_r_versions
test_gxp_validation.py::test_connect_python_versions
test_gxp_validation.py::test_connect_r_package
test_gxp_validation.py::test_connect_python_package
test_gxp_validation.py::test_workbench_r_package
93/121 tests collected (28 deselected) in 0.07s
```

```bash
uv run pytest selftests/test_cli_scaffold.py -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
14 passed
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
712 passed, 3 skipped, 20 warnings
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && echo 'ruff check: OK'
```

```output
All checks passed!
ruff check: OK
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ && echo 'ruff format: OK'
```

```output
148 files already formatted
ruff format: OK
```
