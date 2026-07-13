# Fix #268: skip HTTPS/TLS scenarios on http-only or insecure deployments

*2026-07-09T16:45:23Z by Showboat 0.6.1*
<!-- showboat-id: 284066e8-23f0-4bec-8514-960efb0f3fc2 -->

Bug: when a Posit Team deployment is HTTP-only (e.g. an ephemeral test instance with `tls.insecure=true`), the HTTPS/TLS security scenarios in `test_https.py` and `test_ssl.py` treated that as a **failure** (`assert pc.url.startswith("https://")`) rather than a **skip**. A missing/non-HTTPS URL or an explicit `insecure=true` is a test-environment property, not a security finding — so these scenarios should report N/A, not red.

**Before the fix**, running `vip verify` against a plain `python -m http.server` (no TLS at all) with `--categories security -k "enforces_https or https"`, captured pre-fix:

> `test_product_enforces_https[Connect] SKIPPED` — **FAILED** instead, with:
> `test_product_enforces_https[Connect]: Connect URL is not HTTPS: http://127.0.0.1:8123`
> `assert False`
> `where False = 'http://127.0.0.1:8123'.startswith('https://')`
> `2 failed, 1 skipped, 12 warnings in 1.34s`

(The other pre-existing failure in that run, `test_product_does_not_expose_sensitive_headers`, is unrelated: Python's stock `http.server` genuinely leaks a `Server: SimpleHTTP/...` version header — not in scope for #268.)

**Fix**: three step functions now skip instead of asserting/failing:
- `product_configured_https` (`test_https.py`) — skip when the product URL isn't `https://`.
- `request_http` (`test_ssl.py`) — skip the HTTP→HTTPS redirect check when there's no HTTPS endpoint to redirect to.
- `check_ssl_cert` (`test_ssl.py`) — skip the certificate-validity assertion when `vip_config.insecure` is true (asserting cert validity contradicts the user explicitly disabling verification).

`attempt_tls_connection` (TLS-version enforcement) is intentionally untouched: TLS-version negotiation is still meaningful even with a self-signed cert.

`vip.toml.example`'s `[tls] insecure` doc comment is updated to clarify which scenarios each flag affects.

```bash

mkdir -p /tmp/claude
cat > /tmp/claude/vip-268-repro.toml <<EOF
[connect]
url = "http://127.0.0.1:8123"
[tls]
insecure = true
EOF
uv run python -m http.server 8123 > /tmp/claude/http-server-demo.log 2>&1 &
HTTP_PID=$!
sleep 1
export VIP_CONNECT_API_KEY="dummy-repro-key"
echo "--- security scenarios (HTTPS enforcement) ---"
uv run vip verify --config /tmp/claude/vip-268-repro.toml --categories security -- -k "enforces_https" -v 2>&1 | grep -E "SKIPPED|passed|failed|skipped" | sed -E "s/ in [0-9.]*s//; s/ \[[ 0-9]+%\]//" | sort
echo "--- cross-product scenarios (SSL) ---"
uv run vip verify --config /tmp/claude/vip-268-repro.toml --categories cross-product -- -k "ssl" -v 2>&1 | grep -E "SKIPPED|passed|failed|skipped" | sed -E "s/ in [0-9.]*s//; s/ \[[ 0-9]+%\]//" | sort
kill -9 $HTTP_PID 2>/dev/null

```

```output
--- security scenarios (HTTPS enforcement) ---
======================= 2 skipped, 12 warnings ========================
src/vip_tests/security/test_https.py::test_product_enforces_https[Connect] <- .venv/lib/python3.12/site-packages/pytest_bdd/scenario.py SKIPPED
--- cross-product scenarios (SSL) ---
======================= 4 skipped, 12 warnings ========================
src/vip_tests/cross_product/test_ssl.py::test_http_redirects_to_https_for_product[Connect] <- .venv/lib/python3.12/site-packages/pytest_bdd/scenario.py SKIPPED
src/vip_tests/cross_product/test_ssl.py::test_ssl_certificate_is_valid_for_product[Connect] <- .venv/lib/python3.12/site-packages/pytest_bdd/scenario.py SKIPPED
src/vip_tests/cross_product/test_ssl.py::test_tls_12_or_higher_is_enforced_for_product[Connect] <- .venv/lib/python3.12/site-packages/pytest_bdd/scenario.py SKIPPED
```

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ && uv run ruff format --check src/ src/vip_tests/ selftests/ examples/
```

```output
All checks passed!
152 files already formatted
```

```bash
uv run pytest selftests/ -q --ignore=selftests/test_load_engine.py 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
879 passed, 22 warnings
```

`selftests/test_load_engine.py` is excluded above: it contains wall-clock-timing assertions (`TestThreadpool.test_all_succeed`, `TestAutoRouting.test_small_uses_threadpool`) that are flaky independent of this change — confirmed by running the same tests on an unmodified `main` checkout, where they fail identically. The full `uv run pytest selftests/ -q` (including that file) reports `2 failed, 902 passed, 3 skipped`, both failures in `test_load_engine.py`.

```bash
uv run pytest src/vip_tests/ --collect-only -q 2>&1 | tail -1 | sed -E 's/ in [0-9.]+s//'
```

```output
6/133 tests collected (127 deselected)
```
