"""Tests for vip.verify.job module."""

from __future__ import annotations

import inspect
import json
from unittest.mock import MagicMock, patch


class TestCreateJobSignature:
    def test_no_interactive_auth_parameter(self):
        from vip.verify.job import create_job

        sig = inspect.signature(create_job)
        assert "interactive_auth" not in sig.parameters

    def test_expected_parameters_present(self):
        from vip.verify.job import create_job

        sig = inspect.signature(create_job)
        expected = {
            "name",
            "namespace",
            "config_map_name",
            "image",
            "categories",
            "filter_expr",
            "timeout_seconds",
            "verbose",
        }
        assert expected == set(sig.parameters)


def _capture_job_spec(**kwargs) -> dict:
    """Call create_job with mocked subprocess and return the parsed Job spec."""
    captured: list[str] = []

    def fake_run(cmd, **run_kwargs):
        if "input" in run_kwargs:
            captured.append(run_kwargs["input"])
        result = MagicMock()
        result.returncode = 0
        return result

    with patch("vip.verify.job.subprocess.run", side_effect=fake_run):
        from vip.verify.job import create_job

        create_job(
            name=kwargs.get("name", "test-job"),
            namespace=kwargs.get("namespace", "posit-team"),
            config_map_name=kwargs.get("config_map_name", "test-cm"),
            image=kwargs.get("image", "ghcr.io/posit-dev/vip:latest"),
            categories=kwargs.get("categories"),
            filter_expr=kwargs.get("filter_expr"),
            timeout_seconds=kwargs.get("timeout_seconds", 840),
            verbose=kwargs.get("verbose", False),
        )

    assert captured, "subprocess.run was never called with job JSON"
    return json.loads(captured[0])


class TestCreateJobEnvFrom:
    """Verify that create_job always mounts the vip-test-credentials Secret."""

    def test_env_from_always_present(self):
        spec = _capture_job_spec()
        container = spec["spec"]["template"]["spec"]["containers"][0]
        assert "envFrom" in container
        assert len(container["envFrom"]) >= 1

    def test_credentials_secret_always_mounted(self):
        spec = _capture_job_spec()
        container = spec["spec"]["template"]["spec"]["containers"][0]
        secret_names = [
            entry["secretRef"]["name"] for entry in container["envFrom"] if "secretRef" in entry
        ]
        assert "vip-test-credentials" in secret_names

    def test_credentials_secret_is_optional(self):
        spec = _capture_job_spec()
        container = spec["spec"]["template"]["spec"]["containers"][0]
        for entry in container["envFrom"]:
            if entry.get("secretRef", {}).get("name") == "vip-test-credentials":
                assert entry["secretRef"].get("optional") is True
                return
        raise AssertionError("vip-test-credentials secretRef not found in envFrom")

    def test_env_from_with_categories(self):
        """envFrom is still present when categories are specified."""
        spec = _capture_job_spec(categories="connect")
        container = spec["spec"]["template"]["spec"]["containers"][0]
        secret_names = [
            entry["secretRef"]["name"] for entry in container["envFrom"] if "secretRef" in entry
        ]
        assert "vip-test-credentials" in secret_names


class TestCreateJobFilterExpr:
    """Verify that create_job forwards the filter_expr as pytest -k."""

    def test_filter_expr_adds_k_flag(self):
        spec = _capture_job_spec(filter_expr="test_login")
        args = spec["spec"]["template"]["spec"]["containers"][0]["args"]
        k_index = args.index("-k")
        assert args[k_index + 1] == "test_login"

    def test_no_filter_expr_omits_k_flag(self):
        spec = _capture_job_spec()
        args = spec["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "-k" not in args

    def test_filter_expr_with_categories(self):
        spec = _capture_job_spec(categories="connect", filter_expr="test_login and not saml")
        args = spec["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "-m" in args
        assert "-k" in args
        k_index = args.index("-k")
        assert args[k_index + 1] == "test_login and not saml"


class TestCreateJobVerbose:
    """Verify that create_job forwards the verbose flag as --vip-verbose."""

    def test_verbose_adds_vip_verbose_flag(self):
        spec = _capture_job_spec(verbose=True)
        args = spec["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "--vip-verbose" in args

    def test_no_verbose_omits_vip_verbose_flag(self):
        spec = _capture_job_spec(verbose=False)
        args = spec["spec"]["template"]["spec"]["containers"][0]["args"]
        assert "--vip-verbose" not in args


def test_pytest_args_no_tb_flag():
    """The K8s job should not hardcode --tb=short; the plugin controls traceback format."""
    import inspect

    from vip.verify.job import create_job

    source = inspect.getsource(create_job)
    assert "--tb=short" not in source
