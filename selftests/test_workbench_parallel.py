"""Selftests for #484 Workbench parallelization: login lock + hybrid grouping."""

from __future__ import annotations

import logging

from filelock import FileLock

from vip_tests.workbench import conftest as wb


class TestOidcLoginLock:
    def test_lock_path_is_stable_and_url_scoped(self, tmp_path):
        a1 = wb._login_lock_path("https://wb.example.com")
        a2 = wb._login_lock_path("https://wb.example.com")
        b = wb._login_lock_path("https://other.example.com")
        assert a1 == a2  # stable for the same URL
        assert a1 != b  # distinct deployments get distinct locks
        assert a1.name.endswith(".lock")

    def test_lock_serializes_then_releases(self):
        url = "https://wb.example.com/serialize"
        with wb.oidc_login_lock(url):
            pass
        # Lock released: a fresh instance can acquire immediately.
        other = FileLock(str(wb._login_lock_path(url)))
        other.acquire(timeout=1)
        other.release()

    def test_lock_proceeds_on_timeout(self, caplog):
        url = "https://wb.example.com/contended"
        blocker = FileLock(str(wb._login_lock_path(url)))
        blocker.acquire()
        try:
            entered = False
            with caplog.at_level(logging.WARNING):
                with wb.oidc_login_lock(url, timeout=0.2):
                    entered = True
            assert entered  # proceeded despite not holding the lock
            assert "proceeding without it" in caplog.text
        finally:
            blocker.release()


class _FakeButton:
    def __init__(self):
        self.clicked = False

    def click(self):
        self.clicked = True


class _FakeLogo:
    def __init__(self, *, appears: bool):
        self._appears = appears

    def wait_for(self, *, state, timeout):  # noqa: ARG002 - mirrors Playwright signature
        if not self._appears:
            raise RuntimeError("homepage never appeared")


class TestSilentSsoSignin:
    def test_returns_true_and_uses_lock_when_homepage_appears(self, monkeypatch):
        used = {"locked": False}

        import contextlib

        @contextlib.contextmanager
        def _spy_lock(url):
            used["locked"] = True
            used["url"] = url
            yield

        monkeypatch.setattr(wb, "oidc_login_lock", _spy_lock)
        button = _FakeButton()
        ok = wb._silent_sso_signin(button, _FakeLogo(appears=True), "https://wb.example.com")
        assert ok is True
        assert button.clicked is True
        assert used["locked"] is True
        assert used["url"] == "https://wb.example.com"

    def test_returns_false_when_homepage_never_appears(self, monkeypatch):
        import contextlib

        monkeypatch.setattr(wb, "oidc_login_lock", lambda url: contextlib.nullcontext())
        ok = wb._silent_sso_signin(_FakeButton(), _FakeLogo(appears=False), "https://wb.x")
        assert ok is False
