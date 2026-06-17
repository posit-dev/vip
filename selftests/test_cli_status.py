"""Tests for run_status and _collect_status in vip.cli."""

from __future__ import annotations

import argparse
import json
import sys
from unittest.mock import MagicMock, patch


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace for run_status."""
    defaults = {
        "config": None,
        "json": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_config(
    connect_url: str = "",
    connect_configured: bool = False,
    workbench_url: str = "",
    workbench_configured: bool = False,
    pm_url: str = "",
    pm_configured: bool = False,
) -> MagicMock:
    """Build a minimal VIPConfig mock for run_status."""
    config = MagicMock()

    connect = MagicMock()
    connect.is_configured = connect_configured
    connect.url = connect_url
    connect.api_key = "test-key"
    config.connect = connect

    workbench = MagicMock()
    workbench.is_configured = workbench_configured
    workbench.url = workbench_url
    workbench.api_key = "test-key"
    config.workbench = workbench

    pm = MagicMock()
    pm.is_configured = pm_configured
    pm.url = pm_url
    pm.token = "test-token"
    config.package_manager = pm

    return config


class TestCollectStatus:
    """_collect_status returns structured data with no side effects."""

    def test_unconfigured_product_is_skip(self):
        from vip.cli import _collect_status

        config = _make_config()
        result = _collect_status(config)
        assert result["products"]["connect"]["state"] == "skip"
        assert result["products"]["connect"]["configured"] is False
        assert result["products"]["workbench"]["state"] == "skip"
        assert result["products"]["package_manager"]["state"] == "skip"

    def test_unconfigured_product_has_detail_not_configured(self):
        from vip.cli import _collect_status

        config = _make_config()
        result = _collect_status(config)
        assert result["products"]["connect"]["detail"] == "not configured"

    def test_configured_ok_product(self):
        from vip.cli import _collect_status

        config = _make_config(connect_url="https://connect.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            result = _collect_status(config)

        product = result["products"]["connect"]
        assert product["configured"] is True
        assert product["state"] == "ok"
        assert product["url"] == "https://connect.example.com"
        assert product["http_status"] == 200

    def test_configured_fail_product(self):
        from vip.cli import _collect_status

        config = _make_config(connect_url="https://connect.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 503

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            result = _collect_status(config)

        product = result["products"]["connect"]
        assert product["state"] == "fail"
        assert product["http_status"] == 503

    def test_configured_exception_product(self):
        from vip.cli import _collect_status

        config = _make_config(connect_url="https://connect.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.side_effect = ConnectionError("refused")

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            result = _collect_status(config)

        product = result["products"]["connect"]
        assert product["state"] == "fail"
        assert "refused" in product["detail"]
        assert "http_status" not in product

    def test_workbench_configured_ok(self):
        from vip.cli import _collect_status

        config = _make_config(
            workbench_url="https://workbench.example.com", workbench_configured=True
        )

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.workbench.WorkbenchClient", return_value=mock_client):
            result = _collect_status(config)

        assert result["products"]["workbench"]["state"] == "ok"
        assert result["products"]["workbench"]["http_status"] == 200

    def test_package_manager_configured_ok(self):
        from vip.cli import _collect_status

        config = _make_config(pm_url="https://pm.example.com", pm_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.packagemanager.PackageManagerClient", return_value=mock_client):
            result = _collect_status(config)

        assert result["products"]["package_manager"]["state"] == "ok"
        assert result["products"]["package_manager"]["http_status"] == 200

    def test_outcome_ok_when_all_ok_or_skip(self):
        from vip.cli import _collect_status

        config = _make_config(connect_url="https://connect.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            result = _collect_status(config)

        assert result["outcome"] == "ok"
        assert result["exit_status"] == 0

    def test_outcome_fail_when_any_fail(self):
        from vip.cli import _collect_status

        config = _make_config(connect_url="https://connect.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 503

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            result = _collect_status(config)

        assert result["outcome"] == "fail"
        assert result["exit_status"] == 1

    def test_all_skip_is_ok(self):
        from vip.cli import _collect_status

        config = _make_config()
        result = _collect_status(config)
        assert result["outcome"] == "ok"
        assert result["exit_status"] == 0


class TestRunStatusTextMode:
    """Text mode preserves the original format."""

    def _run(self, config, args=None):
        """Run run_status with mocked load_config and sys.exit, return (out, exit_code)."""
        if args is None:
            args = _make_args()
        exit_code_holder = []

        def fake_exit(code=0):
            exit_code_holder.append(code)

        with (
            patch("vip.config.load_config", return_value=config),
            patch("vip.cli.sys.exit", side_effect=fake_exit),
        ):
            import io

            from vip.cli import run_status

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                run_status(args)
            except SystemExit:
                pass
            finally:
                sys.stdout = old_stdout

        return captured.getvalue(), exit_code_holder[0] if exit_code_holder else None

    def test_skip_line_format(self):
        config = _make_config()
        out, _ = self._run(config)
        # Format: "  SKIP  package_manager       not configured"
        assert "SKIP" in out
        assert "not configured" in out

    def test_ok_line_format(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            out, _ = self._run(config)

        assert "OK  " in out
        assert "HTTP 200" in out

    def test_exit_0_when_all_ok_or_skip(self):
        config = _make_config()
        _, code = self._run(config)
        assert code == 0

    def test_exit_1_when_any_fail(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 503

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            _, code = self._run(config)

        assert code == 1

    def test_text_line_width_format(self):
        """Verify the exact column format: '  {STATE:4s}  {name:20s}  {detail}'."""
        config = _make_config()
        out, _ = self._run(config)
        lines = [line for line in out.splitlines() if line.strip()]
        assert len(lines) == 3  # one per product
        for line in lines:
            # Must start with two spaces
            assert line.startswith("  "), f"Line does not start with two spaces: {line!r}"


class TestRunStatusJsonMode:
    """JSON mode emits the documented schema to stdout."""

    def _run_json(self, config):
        """Run run_status with --json flag, return parsed JSON and exit_code."""
        args = _make_args(json=True)
        exit_code_holder = []

        def fake_exit(code=0):
            exit_code_holder.append(code)
            raise SystemExit(code)

        with (
            patch("vip.config.load_config", return_value=config),
            patch("vip.cli.sys.exit", side_effect=fake_exit),
        ):
            import io

            from vip.cli import run_status

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                run_status(args)
            except SystemExit:
                pass
            finally:
                sys.stdout = old_stdout

        output = captured.getvalue()
        parsed = json.loads(output)
        return parsed, exit_code_holder[0] if exit_code_holder else None

    def test_json_top_level_keys(self):
        config = _make_config()
        parsed, _ = self._run_json(config)
        assert "products" in parsed
        assert "outcome" in parsed
        assert "exit_status" in parsed

    def test_json_products_keys(self):
        config = _make_config()
        parsed, _ = self._run_json(config)
        assert set(parsed["products"].keys()) == {"connect", "workbench", "package_manager"}

    def test_json_unconfigured_skip(self):
        config = _make_config()
        parsed, _ = self._run_json(config)
        for name in ("connect", "workbench", "package_manager"):
            product = parsed["products"][name]
            assert product["configured"] is False
            assert product["state"] == "skip"
            assert product["detail"] == "not configured"
            assert "url" not in product
            assert "http_status" not in product

    def test_json_configured_ok(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            parsed, _ = self._run_json(config)

        product = parsed["products"]["connect"]
        assert product["configured"] is True
        assert product["state"] == "ok"
        assert product["url"] == "https://c.example.com"
        assert product["http_status"] == 200

    def test_json_configured_fail_http(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 503

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            parsed, _ = self._run_json(config)

        product = parsed["products"]["connect"]
        assert product["state"] == "fail"
        assert product["http_status"] == 503

    def test_json_configured_exception(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.side_effect = ConnectionError("connection refused")

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            parsed, _ = self._run_json(config)

        product = parsed["products"]["connect"]
        assert product["state"] == "fail"
        assert "connection refused" in product["detail"]
        assert "http_status" not in product

    def test_json_outcome_ok_all_skip(self):
        config = _make_config()
        parsed, code = self._run_json(config)
        assert parsed["outcome"] == "ok"
        assert parsed["exit_status"] == 0
        assert code == 0

    def test_json_outcome_ok_with_ok_product(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 200

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            parsed, code = self._run_json(config)

        assert parsed["outcome"] == "ok"
        assert parsed["exit_status"] == 0
        assert code == 0

    def test_json_outcome_fail_any_fail(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.return_value = 503

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            parsed, code = self._run_json(config)

        assert parsed["outcome"] == "fail"
        assert parsed["exit_status"] == 1
        assert code == 1

    def test_json_exit_1_on_exception(self):
        config = _make_config(connect_url="https://c.example.com", connect_configured=True)

        mock_client = MagicMock()
        mock_client.health.side_effect = OSError("timeout")

        with patch("vip.clients.connect.ConnectClient", return_value=mock_client):
            parsed, code = self._run_json(config)

        assert parsed["exit_status"] == 1
        assert code == 1

    def test_json_is_valid_json(self):
        """stdout must be valid JSON — no extra human-readable text mixed in."""
        config = _make_config()
        args = _make_args(json=True)

        with (
            patch("vip.config.load_config", return_value=config),
            patch("vip.cli.sys.exit"),
        ):
            import io

            from vip.cli import run_status

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                run_status(args)
            except SystemExit:
                pass
            finally:
                sys.stdout = old_stdout

        # Must not raise
        json.loads(captured.getvalue())

    def test_json_mode_no_human_text_mixed_in(self):
        """JSON mode must not print any human-readable lines outside the JSON object."""
        config = _make_config()
        args = _make_args(json=True)

        with (
            patch("vip.config.load_config", return_value=config),
            patch("vip.cli.sys.exit"),
        ):
            import io

            from vip.cli import run_status

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                run_status(args)
            except SystemExit:
                pass
            finally:
                sys.stdout = old_stdout

        output = captured.getvalue().strip()
        # Should be a single JSON object, not multiple lines of mixed text
        parsed = json.loads(output)
        assert isinstance(parsed, dict)
