"""Selftests for the transient packrat/CDN deploy retry (vip#553).

Verifies the narrow signature matcher (``_is_transient_packrat_cdn_failure``)
against real captured failure text, and verifies ``wait_for_deploy`` retries
at most once, only for a matching failure, and still fails the suite when
the retry doesn't help.

No real network connections are made: ``connect_client`` is a stand-in with
mocked ``wait_for_task`` and a ``redeploy`` callable installed on
``deploy_state``, exactly as the real step functions install it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Imported at collection time, on purpose -- see the comment in
# test_publish_to_connect_fixtures.py for why importing test_content_deploy
# from inside a test body (rather than at module scope) can raise IndexError
# under pytester-based selftests sharing an xdist worker.
from vip_tests.connect import test_content_deploy as tcd

# ---------------------------------------------------------------------------
# Real captured failure text (run 30398775778, connect-smoke.yml, 2026.06.0 leg)
# ---------------------------------------------------------------------------

# Verbatim excerpt from the failing test_deploy_shiny task output: fontawesome
# fails twice (packrat's own internal retry also fails) and packrat aborts.
_REAL_TRANSIENT_CDN_FAILURE = """\
Installing fontawesome (0.5.3) ...
curl: (35) OpenSSL SSL_connect: Connection reset by peer in connection to rspm-sync.rstudio.com:443
curl: HTTP 307 https://rspm-sync.rstudio.com/bin/4.5-jammy/950a997e6416de6f370d9578e91f677b6ad42a6d840640ad5d612464f65f7845.tar.gz
Error in download.file(url, destfile, method, mode = "wb", ...) :
  'curl' call had nonzero exit status
Warning in download.packages(name, destdir = destdir, repos = repos, type = type,  :
  download of package 'fontawesome' failed
curl: (35) OpenSSL SSL_connect: Connection reset by peer in connection to rspm-sync.rstudio.com:443
curl: HTTP 307 https://rspm-sync.rstudio.com/bin/4.5-jammy/950a997e6416de6f370d9578e91f677b6ad42a6d840640ad5d612464f65f7845.tar.gz
Error in download.file(url, destfile, method, mode = "wb", ...) :
  'curl' call had nonzero exit status
Warning in download.packages(name, destdir = destdir, repos = repos, type = type,  :
  download of package 'fontawesome' failed
Error in getSourceForPkgRecord(pkgRecord, srcDir(project), availablePackagesSource(repos = repos), \
: Failed to download current version of fontawesome(0.5.3)

Unable to fully restore the R packages associated with this deployment.
Please review the preceding messages to determine which package
encountered installation difficulty and the cause of the failure.
"""

# Genuinely different failure shapes -- none of these are network-related.
_BAD_MANIFEST_FAILURE = """\
Error: Invalid manifest: unknown appmode 'python-fastapi-v2'
manifest.json failed schema validation
Job completed with failure
"""

_WRONG_ENTRYPOINT_FAILURE = """\
jupyter nbconvert: error: the following arguments are required: notebook
usage: jupyter nbconvert [-h] [notebook]
Job completed with failure
"""

_APP_CRASH_FAILURE = """\
Traceback (most recent call last):
  File "app.py", line 3, in <module>
    import nonexistent_module
ModuleNotFoundError: No module named 'nonexistent_module'
Job completed with failure
"""

_UNRELATED_CODE_NONZERO_FAILURE = """\
Error: license check failed: no seats available for this content type
Job completed with failure
"""


# ---------------------------------------------------------------------------
# _is_transient_packrat_cdn_failure -- positive and negative cases
# ---------------------------------------------------------------------------


class TestIsTransientPackratCdnFailure:
    def test_matches_real_captured_failure(self):
        """The exact signature from run 30398775778 must match."""
        assert tcd._is_transient_packrat_cdn_failure(_REAL_TRANSIENT_CDN_FAILURE) is True

    @pytest.mark.parametrize(
        "output",
        [
            _BAD_MANIFEST_FAILURE,
            _WRONG_ENTRYPOINT_FAILURE,
            _APP_CRASH_FAILURE,
            _UNRELATED_CODE_NONZERO_FAILURE,
            "",
        ],
        ids=["bad-manifest", "wrong-entrypoint", "app-crash", "unrelated-nonzero", "empty"],
    )
    def test_does_not_match_other_failures(self, output):
        """A predicate that never rejects proves nothing -- these must all be False."""
        assert tcd._is_transient_packrat_cdn_failure(output) is False

    def test_requires_all_three_parts_not_any_one(self):
        """Each part alone, or any two of three, must NOT be sufficient."""
        curl_code_only = "curl: (35) OpenSSL SSL_connect: Connection reset by peer"
        host_only = "talking to rspm-sync.rstudio.com about packages"
        restore_text_only = (
            "Unable to fully restore the R packages associated with this deployment."
        )
        curl_and_host_no_restore_text = curl_code_only + " " + host_only
        curl_and_restore_no_host = curl_code_only + " " + restore_text_only
        host_and_restore_no_curl = host_only + " " + restore_text_only

        for output in (
            curl_code_only,
            host_only,
            restore_text_only,
            curl_and_host_no_restore_text,
            curl_and_restore_no_host,
            host_and_restore_no_curl,
        ):
            assert tcd._is_transient_packrat_cdn_failure(output) is False, (
                f"Partial signature incorrectly matched: {output!r}"
            )

        # All three together must match.
        assert (
            tcd._is_transient_packrat_cdn_failure(
                curl_code_only + " " + host_only + " " + restore_text_only
            )
            is True
        )

    def test_does_not_confuse_two_digit_curl_codes(self):
        """'curl: (7)' must not spuriously match inside e.g. 'curl: (17)'."""
        output = (
            "curl: (17) some unrelated curl error\n"
            "rspm-sync.rstudio.com\n"
            "Unable to fully restore the R packages"
        )
        assert tcd._is_transient_packrat_cdn_failure(output) is False


# ---------------------------------------------------------------------------
# wait_for_deploy -- retry orchestration
# ---------------------------------------------------------------------------


def _vip_config(timeout: float = 5.0):
    return SimpleNamespace(connect=SimpleNamespace(deploy_timeout=timeout))


def _finished_task(*, code: int, output: list[str], error: str = "deploy failed") -> dict:
    return {"finished": True, "code": code, "output": output, "error": error}


class TestWaitForDeployRetry:
    def test_matching_failure_is_retried_and_then_succeeds(self):
        """First attempt hits the transient signature; the retry succeeds; no
        pytest.fail is raised; wait_for_task is called exactly twice."""
        connect_client = MagicMock()
        connect_client.wait_for_task.side_effect = [
            _finished_task(code=1, output=_REAL_TRANSIENT_CDN_FAILURE.splitlines()),
            _finished_task(code=0, output=["OK"]),
        ]
        redeploy = MagicMock(return_value={"task_id": "task-2"})
        deploy_state = {"task_id": "task-1", "name": "vip-shiny-test", "redeploy": redeploy}

        tcd.wait_for_deploy(connect_client, deploy_state, _vip_config())

        assert connect_client.wait_for_task.call_count == 2
        redeploy.assert_called_once()
        # The second wait_for_task call must poll the *new* task from redeploy.
        assert connect_client.wait_for_task.call_args_list[1].args[0] == "task-2"

    def test_second_matching_failure_still_fails(self):
        """Both attempts hit the transient signature: the suite still fails,
        and only one retry is attempted (not an unbounded loop)."""
        connect_client = MagicMock()
        connect_client.wait_for_task.side_effect = [
            _finished_task(code=1, output=_REAL_TRANSIENT_CDN_FAILURE.splitlines()),
            _finished_task(code=1, output=_REAL_TRANSIENT_CDN_FAILURE.splitlines()),
        ]
        redeploy = MagicMock(return_value={"task_id": "task-2"})
        deploy_state = {"task_id": "task-1", "name": "vip-shiny-test", "redeploy": redeploy}

        with pytest.raises(pytest.fail.Exception):
            tcd.wait_for_deploy(connect_client, deploy_state, _vip_config())

        assert connect_client.wait_for_task.call_count == 2
        redeploy.assert_called_once()  # exactly one retry, never a second

    def test_non_matching_failure_is_not_retried(self):
        """A failure that doesn't match the signature fails on the first
        attempt, with no redeploy call at all -- assert on the call count,
        not just the outcome."""
        connect_client = MagicMock()
        connect_client.wait_for_task.side_effect = [
            _finished_task(code=1, output=_APP_CRASH_FAILURE.splitlines()),
        ]
        redeploy = MagicMock(return_value={"task_id": "task-2"})
        deploy_state = {"task_id": "task-1", "name": "vip-fastapi-test", "redeploy": redeploy}

        with pytest.raises(pytest.fail.Exception):
            tcd.wait_for_deploy(connect_client, deploy_state, _vip_config())

        assert connect_client.wait_for_task.call_count == 1
        redeploy.assert_not_called()

    def test_matching_failure_without_redeploy_fails_immediately(self):
        """If a caller never set deploy_state['redeploy'] (shouldn't happen in
        practice), a matching failure must still fail cleanly instead of
        raising KeyError."""
        connect_client = MagicMock()
        connect_client.wait_for_task.side_effect = [
            _finished_task(code=1, output=_REAL_TRANSIENT_CDN_FAILURE.splitlines()),
        ]
        deploy_state = {"task_id": "task-1", "name": "vip-shiny-test"}

        with pytest.raises(pytest.fail.Exception):
            tcd.wait_for_deploy(connect_client, deploy_state, _vip_config())

        assert connect_client.wait_for_task.call_count == 1

    def test_successful_first_attempt_never_calls_redeploy(self):
        """The common case: deploy succeeds first try, retry machinery never engages."""
        connect_client = MagicMock()
        connect_client.wait_for_task.side_effect = [_finished_task(code=0, output=["OK"])]
        redeploy = MagicMock(return_value={"task_id": "task-2"})
        deploy_state = {"task_id": "task-1", "name": "vip-quarto-test", "redeploy": redeploy}

        tcd.wait_for_deploy(connect_client, deploy_state, _vip_config())

        assert connect_client.wait_for_task.call_count == 1
        redeploy.assert_not_called()

    def test_unfinished_task_fails_without_retry(self):
        """A deploy that never finishes (timeout) is unrelated to the CDN
        retry and must fail exactly as before -- no redeploy attempt."""
        connect_client = MagicMock()
        connect_client.wait_for_task.side_effect = [
            {"finished": False, "output": ["still running"]},
        ]
        redeploy = MagicMock(return_value={"task_id": "task-2"})
        deploy_state = {"task_id": "task-1", "name": "vip-shiny-test", "redeploy": redeploy}

        with pytest.raises(pytest.fail.Exception):
            tcd.wait_for_deploy(connect_client, deploy_state, _vip_config())

        assert connect_client.wait_for_task.call_count == 1
        redeploy.assert_not_called()
