# fix(connect): redact license keys from system check report

*2026-04-10T17:37:52Z by Showboat 0.6.1*
<!-- showboat-id: 71fb0583-0537-4f57-b8db-b2709ae5774e -->

Connect system check results can include license keys in output/error fields. Before this fix, those values were written verbatim to connect_system_checks.json and rendered in the Quarto report. The fix adds _redact_license_outputs() in test_system_checks.py that replaces output/error with '[redacted]' for any result whose group or test name contains 'license' (case-insensitive). The safe copy is now written to the artifact file instead of the raw API response.

```bash
uv run pytest selftests/test_system_checks.py -v 2>&1 | tail -20
```

```output
rootdir: /home/runner/work/vip/vip
configfile: pyproject.toml
plugins: base-url-2.1.0, bdd-8.1.0, shiny-1.5.1, playwright-0.7.2, xdist-3.8.0, posit-vip-0.21.1, anyio-4.12.1
collecting ... collected 13 items

selftests/test_system_checks.py::TestRedactLicenseOutputs::test_license_group_is_redacted PASSED [  7%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_license_in_test_name_is_redacted PASSED [ 15%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_non_license_check_is_not_redacted PASSED [ 23%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_case_insensitive_group_match PASSED [ 30%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_case_insensitive_test_name_match PASSED [ 38%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_mixed_results_selective_redaction PASSED [ 46%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_original_results_are_not_mutated PASSED [ 53%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_empty_list PASSED [ 61%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_missing_group_key PASSED [ 69%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_missing_test_key PASSED [ 76%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_non_license_checks_pass_through[-] PASSED [ 84%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_non_license_checks_pass_through[Runtime-r_version] PASSED [ 92%]
selftests/test_system_checks.py::TestRedactLicenseOutputs::test_non_license_checks_pass_through[Database-postgres] PASSED [100%]

============================== 13 passed in 0.03s ==============================
```

```bash
uv tool run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```
