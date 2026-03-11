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
            "timeout_seconds",
        }
        assert expected == set(sig.parameters)


class TestCreateJobEnvFrom:
    """Verify that create_job always mounts the vip-test-credentials Secret."""

    def _capture_job_spec(self, **kwargs) -> dict:
        """Call create_job with mocked subprocess and return parsed Job spec."""
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
                timeout_seconds=kwargs.get("timeout_seconds", 840),
            )

        assert captured, "subprocess.run was never called with job JSON"
        # The second call is the Job (first is the ConfigMap if any; here
        # create_job only calls kubectl once for the Job itself).
        return json.loads(captured[0])

    def test_env_from_always_present(self):
        spec = self._capture_job_spec()
        container = spec["spec"]["template"]["spec"]["containers"][0]
        assert "envFrom" in container
        assert len(container["envFrom"]) >= 1

    def test_credentials_secret_always_mounted(self):
        spec = self._capture_job_spec()
        container = spec["spec"]["template"]["spec"]["containers"][0]
        secret_names = [
            entry["secretRef"]["name"] for entry in container["envFrom"] if "secretRef" in entry
        ]
        assert "vip-test-credentials" in secret_names

    def test_credentials_secret_is_optional(self):
        spec = self._capture_job_spec()
        container = spec["spec"]["template"]["spec"]["containers"][0]
        for entry in container["envFrom"]:
            if entry.get("secretRef", {}).get("name") == "vip-test-credentials":
                assert entry["secretRef"].get("optional") is True
                return
        raise AssertionError("vip-test-credentials secretRef not found in envFrom")

    def test_env_from_with_categories(self):
        """envFrom is still present when categories are specified."""
        spec = self._capture_job_spec(categories="connect")
        container = spec["spec"]["template"]["spec"]["containers"][0]
        secret_names = [
            entry["secretRef"]["name"] for entry in container["envFrom"] if "secretRef" in entry
        ]
        assert "vip-test-credentials" in secret_names
