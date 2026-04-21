# Fix: TLS test distinguishes cert-trust from version-enforcement failures

*2026-04-20T21:08:19Z by Showboat 0.6.1*
<!-- showboat-id: 71f05fdf-f583-4977-877f-0bc769c7534a -->

Issue #175: behind an SSL-terminating ALB, the TLS-version test failed with a cert-verify error that was reported as a TLS 1.2 enforcement failure. This change uses the system CA bundle for the TLS-version attempts, classifies cert-verify failures separately, and surfaces actionable SSL_CERT_FILE / certifi guidance.

```bash
uv run pytest selftests/test_ssl_helper.py -v --no-header 2>&1 | grep -E 'PASSED|FAILED|ERROR' | sed 's/ \[[ 0-9]*%\]//'
```

```output
selftests/test_ssl_helper.py::test_attempt_tls_returns_connected_on_success PASSED
selftests/test_ssl_helper.py::test_attempt_tls_classifies_cert_verify_failure PASSED
selftests/test_ssl_helper.py::test_attempt_tls_classifies_plain_ssl_error_as_rejected PASSED
selftests/test_ssl_helper.py::test_attempt_tls_classifies_oserror_as_rejected PASSED
selftests/test_ssl_helper.py::test_attempt_tls_raises_connect_error_when_host_unreachable PASSED
selftests/test_ssl_helper.py::test_attempt_tls_classifies_context_config_failure_as_client_unsupported PASSED
selftests/test_ssl_helper.py::test_old_tls_rejected_passes_when_both_refused PASSED
selftests/test_ssl_helper.py::test_old_tls_rejected_fails_on_connected_tls_1_0 PASSED
selftests/test_ssl_helper.py::test_old_tls_rejected_fails_on_cert_verify_for_legacy_version PASSED
selftests/test_ssl_helper.py::test_modern_tls_succeeds_passes_when_connected PASSED
selftests/test_ssl_helper.py::test_modern_tls_succeeds_surfaces_cert_verify_with_guidance PASSED
selftests/test_ssl_helper.py::test_modern_tls_succeeds_reports_plain_rejection_clearly PASSED
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
265 passed, 6 warnings
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
102 files already formatted
```
