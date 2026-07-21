"""Selftests for #484 Workbench parallelization: login lock + hybrid grouping."""

from __future__ import annotations

import logging
from pathlib import Path

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


class TestWorkbenchGroupName:
    def test_ide_marker_wins(self):
        assert wb._workbench_group_name({"rstudio"}, "test_ide_launch") == "workbench_ide_rstudio"
        assert wb._workbench_group_name({"positron"}, "test_ide_launch") == "workbench_ide_positron"

    def test_non_ide_groups_by_module_stripping_test_prefix(self):
        assert wb._workbench_group_name(set(), "test_packages") == "workbench_packages"
        assert wb._workbench_group_name(set(), "test_git_ops") == "workbench_git_ops"

    def test_module_without_test_prefix_kept_verbatim(self):
        assert wb._workbench_group_name(set(), "chronicle_probe") == "workbench_chronicle_probe"


class _FakeMarker:
    def __init__(self, name):
        self.name = name


class _FakeItem:
    def __init__(self, path: Path, marker_names):
        self.path = path
        self.own_markers = [_FakeMarker("xdist_group"), _FakeMarker("workbench")]
        self._markers = [_FakeMarker(n) for n in marker_names]
        self.added = []

    def iter_markers(self):
        return list(self._markers)

    def add_marker(self, marker):
        # pytest.mark.xdist_group("g") -> mark object with .name and .args
        self.added.append((marker.name, marker.args))


class _FakeConfig:
    def __init__(self, session):
        self._session = session

    @property
    def stash(self):
        cfg = self

        class _Stash:
            def get(self, key, default=None):  # noqa: ARG002
                return cfg._session

        return _Stash()


class TestSessionTimeoutMessage:
    def _base(self, session_name, target_state, timeout_s):
        return (
            f"Session {session_name!r} did not reach {target_state} within {timeout_s}s "
            f"(no {target_state} or terminal status detected)."
        )

    def test_single_worker_is_just_the_base_message(self):
        msg = wb._session_timeout_message("VIP rstudio", "Active", 90, 1)
        assert msg == self._base("VIP rstudio", "Active", 90)
        assert "parallel workers" not in msg

    def test_multiple_workers_appends_capacity_hint(self):
        msg = wb._session_timeout_message("VIP rstudio", "Active", 90, 4)
        assert self._base("VIP rstudio", "Active", 90) in msg
        assert "parallel workers" in msg
        assert "reducing parallelism" in msg


class TestCollectionHook:
    def _wb_dir(self):
        return Path(wb.__file__).parent

    def test_no_auth_session_is_a_noop(self):
        item = _FakeItem(self._wb_dir() / "test_packages.py", [])
        wb.pytest_collection_modifyitems(_FakeConfig(None), [item])
        assert item.added == []  # untouched under password / no-auth

    def test_ide_item_grouped_by_ide(self):
        item = _FakeItem(self._wb_dir() / "test_ide_launch.py", ["workbench", "rstudio"])
        wb.pytest_collection_modifyitems(_FakeConfig(object()), [item])
        assert ("xdist_group", ("workbench_ide_rstudio",)) in item.added
        assert all(m.name != "xdist_group" for m in item.own_markers)  # old group stripped

    def test_non_ide_item_grouped_by_module(self):
        item = _FakeItem(self._wb_dir() / "test_packages.py", ["workbench"])
        wb.pytest_collection_modifyitems(_FakeConfig(object()), [item])
        assert ("xdist_group", ("workbench_packages",)) in item.added

    def test_non_workbench_item_ignored(self):
        item = _FakeItem(Path("/somewhere/connect/test_auth.py"), ["connect"])
        wb.pytest_collection_modifyitems(_FakeConfig(object()), [item])
        assert item.added == []
