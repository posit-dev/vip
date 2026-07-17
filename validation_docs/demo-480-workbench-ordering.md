# test(workbench): intentional Workbench test order (#481/#482)

*2026-07-17T20:42:29Z by Showboat 0.6.1*
<!-- showboat-id: 7bd7451e-6e68-45dd-bcdc-6d3cbee6a1ab -->

The Workbench BDD suite previously collected in plain alphabetical file order, which interleaved foundational tests with dependent ones -- test_ide_extensions.py and test_git_ops.py sorted ahead of test_ide_launch.py, so extension checks and git operations collected before the session-launch tests they depend on even existed in the run order.

This change imposes an intentional order via module-level pytest-order markers (one pytestmark = pytest.mark.order(N) per Workbench test module), composing with the existing xdist_group hook in workbench/conftest.py rather than replacing it:

- rank 10: test_auth (the gate)
- rank 20: test_ide_launch (session launch -- foundational)
- rank 30: test_sessions (session lifecycle)
- rank 40: test_session_capacity, test_session_capacity_k8s
- rank 45: test_session_idle
- rank 50: test_runtime_versions
- rank 60: test_packages, test_data_sources, test_git_ops, test_jobs, test_publish_to_connect, test_chronicle (in-session features; git ops grouped here, after launch, per #482)
- rank 90: test_ide_extensions (last)

#482's config-less public clone for test_git_ops already shipped separately (#483, GitTestConfig default public clone); the only #482 work here is ranking test_git_ops into the rank-60 in-session group so it collects after launch.

```bash
env -u UV_PROJECT uv run --project . pytest selftests/test_workbench_ordering.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR" | sed 's/ *\[ *[0-9]*%\]//' | sort

```

```output
selftests/test_workbench_ordering.py::test_auth_collects_before_ide_launch PASSED
selftests/test_workbench_ordering.py::test_ide_extensions_is_last_workbench_file PASSED
selftests/test_workbench_ordering.py::test_ide_launch_collects_before_git_ops PASSED
selftests/test_workbench_ordering.py::test_ide_launch_collects_before_ide_extensions PASSED
```

```bash
CFG=$TMPDIR/vip-demo.toml; printf '[workbench]\nurl = "https://wb.example.com"\n\n[connect]\nurl = "https://connect.example.com"\n' > "$CFG"; env -u UV_PROJECT uv run --project . pytest src/vip_tests/workbench --collect-only -q --vip-config="$CFG" 2>/dev/null | sed -n 's/::.*//p' | awk -F/ '{print $NF}' | awk '!seen[$0]++'

```

```output
test_auth.py
test_ide_launch.py
test_sessions.py
test_session_capacity.py
test_session_capacity_k8s.py
test_session_idle.py
test_runtime_versions.py
test_chronicle.py
test_data_sources.py
test_git_ops.py
test_jobs.py
test_packages.py
test_publish_to_connect.py
test_ide_extensions.py
```

```bash
env -u UV_PROJECT uv run --project . ruff check src/ src/vip_tests/ selftests/ examples/ && env -u UV_PROJECT uv run --project . ruff format --check src/ src/vip_tests/ selftests/ examples/

```

```output
All checks passed!
161 files already formatted
```
