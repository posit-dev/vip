# Fix: HTTPS redirect test accepts ALB termination

*2026-06-11T15:59:56Z by Showboat 0.6.1*
<!-- showboat-id: cb60ad60-d711-4c3c-88ad-5cf6dc391d6f -->

The SSL redirect test previously only accepted a direct 3xx response with an https:// Location header. Behind an AWS ALB (or similar load balancer), the HTTP→HTTPS upgrade can happen transparently — the client may receive a 200 after the ALB internally redirects, or the redirect chain may differ from a plain 3xx. This caused false failures even when HTTP traffic correctly ended up at HTTPS (confirmed in a browser). The fix adds a fallback: follow the redirect chain (follow_redirects=True) and pass if the final URL scheme is https. The primary 3xx path is preserved so direct-redirect deployments still pass as before.

```bash
uv run ruff check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -5 || echo 'ruff check passed'
```

```output
All checks passed!
```

```bash
uv run ruff format --check src/ src/vip_tests/ selftests/ examples/ 2>&1 | tail -5 || echo 'ruff format passed'
```

```output
143 files already formatted
```

```bash
uv run pytest selftests/ -q 2>&1 | grep -E 'passed|failed|error' | sed 's/ in [0-9.]*s//'
```

```output
685 passed, 3 skipped, 20 warnings
```

```bash
uv run pytest src/vip_tests/ --collect-only -q 2>&1 | grep -E 'selected|error|no tests' | sed 's/ in [0-9.]*s//' | head -5
```

```output
6/113 tests collected (107 deselected)
```

```bash
grep -n 'follow_redirects\|https\|redirect' src/vip_tests/cross_product/test_ssl.py | head -30
```

```output
6:- HTTP not redirecting to HTTPS
40:    if parsed.scheme != "https":
73:# Steps - HTTPS redirect
85:    http_url = product_url.replace("https://", "http://")
90:        resp_no_follow = httpx.get(http_url, follow_redirects=False, timeout=10)
91:        # Also follow redirects to detect ALB / load-balancer patterns where
93:        resp_followed = httpx.get(http_url, follow_redirects=True, timeout=10)
106:@then("the response redirects to HTTPS")
107:def redirects_to_https(http_response):
112:    # Primary path: a standard 3xx redirect with an https:// Location header.
113:    direct_redirect = http_response["status"] in (301, 302, 307, 308) and http_response[
115:    ].startswith("https://")
117:    # Fallback path: following the redirect chain (including ALB/LB transparent
119:    followed_to_https = http_response.get("final_url_scheme") == "https"
121:    assert direct_redirect or followed_to_https, (
122:        f"HTTP did not redirect to HTTPS. "
125:        f"final URL scheme after following redirects: {http_response.get('final_url_scheme')!r}"
131:    # This step is an alternative - if HTTP redirected, that's fine too.
229:    if parsed.scheme != "https":
```
