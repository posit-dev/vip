"""Selftests for #484 Workbench parallelization: login lock + hybrid grouping."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from filelock import FileLock
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

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

    def test_lock_released_when_body_raises(self):
        # The lock must release even if the protected body raises, or a stale cross-worker
        # lock file would stall every other worker for the full timeout on each login.
        url = "https://wb.example.com/raises"
        with pytest.raises(RuntimeError):
            with wb.oidc_login_lock(url):
                raise RuntimeError("boom inside the lock")
        other = FileLock(str(wb._login_lock_path(url)))
        other.acquire(timeout=1)  # would block/raise Timeout if the lock leaked
        other.release()

    def test_lock_proceeds_on_timeout(self, caplog):
        url = "https://wb.example.com/contended"
        blocker = FileLock(str(wb._login_lock_path(url)))
        blocker.acquire()
        try:
            entered = False
            with caplog.at_level(logging.WARNING):
                # Surfaced as a warning too, so contention is visible in pytest's summary.
                with pytest.warns(UserWarning, match="proceeding without it"):
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
            # Model the real timeout: Playwright raises PlaywrightTimeoutError, which is
            # what _silent_sso_signin catches. A different exception type must propagate.
            raise PlaywrightTimeoutError("homepage never appeared")


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

    def test_non_playwright_error_propagates(self, monkeypatch):
        # A crashed page / bug in the helper must surface as a real failure, not be
        # laundered into False (which the caller turns into a misleading graceful skip).
        import contextlib

        class _BrokenLogo:
            def wait_for(self, *, state, timeout):  # noqa: ARG002
                raise RuntimeError("page crashed mid-login")

        monkeypatch.setattr(wb, "oidc_login_lock", lambda url: contextlib.nullcontext())
        with pytest.raises(RuntimeError, match="page crashed"):
            wb._silent_sso_signin(_FakeButton(), _BrokenLogo(), "https://wb.x")


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


class TestRealMarkerMechanics:
    """Guard the assumption the fakes above cannot: that the hook's strip + add_marker
    sequence is actually visible to pytest-xdist, which reads xdist_group via
    ``get_closest_marker`` and concatenates *every* xdist_group mark it finds via
    ``iter_markers``. Exercised on a real pytest ``Item``, not a fake."""

    def test_regroup_wins_via_get_closest_marker_and_leaves_no_duplicate(self, pytester):
        import pytest as _pytest

        # Disable the vip plugin for the nested collection: its own _assign_xdist_group
        # would inject a "general" group and obscure the mechanic under test.
        modcol = pytester.getmodulecol("def test_x(): pass", configargs=["-p", "no:vip"])
        (item,) = pytester.genitems([modcol])
        # Simulate a pre-existing group, then apply exactly the hook's two operations.
        item.add_marker(_pytest.mark.xdist_group("workbench"))
        item.own_markers = [m for m in item.own_markers if m.name != "xdist_group"]
        item.add_marker(_pytest.mark.xdist_group("workbench_packages"))

        # get_closest_marker is the path LoadGroupScheduling reads — it must see the new group.
        marker = item.get_closest_marker("xdist_group")
        assert marker is not None
        assert marker.args == ("workbench_packages",)
        # And no leftover duplicate, or xdist would glue both names into one composite group.
        groups = [m.args[0] for m in item.iter_markers("xdist_group")]
        assert groups == ["workbench_packages"]
