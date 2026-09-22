"""Locust user classes for realistic Posit Team user simulation.

Each product has a dedicated ``HttpUser`` subclass that models real user
behavior: multiple endpoints with weighted task frequencies and think-time
between requests.

These classes are used by :func:`vip.load_engine.run_user_simulation` when
``load_test_tool`` is ``"locust"``.
"""

from __future__ import annotations

try:
    from locust import HttpUser, between, task
except ImportError as _err:
    msg = (
        'locust is required for user simulation: install the "load" extra '
        '(`uv pip install "posit-vip[load]"` for an installed package, '
        "or `uv sync --extra load` from a source checkout)"
    )
    raise ImportError(msg) from _err


class ConnectUser(HttpUser):
    """Simulates a Connect user browsing content and checking server info.

    Task weights reflect real usage: browsing content is the most common
    action, followed by viewing individual items and checking user info.
    Write operations (deploy) are rare.
    """

    wait_time = between(1, 3)
    # host and headers are set dynamically by the load engine before spawning.
    abstract = True

    def on_start(self) -> None:
        """Authenticate and seed data for the session."""
        self._api_key = getattr(self.environment, "_vip_credentials", {}).get("api_key", "")
        self._headers = {"Authorization": f"Key {self._api_key}"}
        # Pre-fetch a content GUID for single-item lookups.
        self._content_guid = None
        try:
            resp = self.client.get(
                "/__api__/v1/content",
                headers=self._headers,
                name="/__api__/v1/content",
            )
            if resp.status_code == 200:
                items = resp.json()
                if items:
                    self._content_guid = items[0].get("guid")
        except Exception:  # noqa: BLE001
            # Best-effort priming — a failed pre-fetch just leaves
            # ``_content_guid`` unset; it must not abort the simulated user.
            pass

    @task(10)
    def list_content(self) -> None:
        """Fetch the content listing."""
        self.client.get("/__api__/v1/content", headers=self._headers)

    @task(8)
    def get_content_item(self) -> None:
        """Fetch the detail page for the content item found by ``on_start``, if any."""
        if self._content_guid:
            self.client.get(
                f"/__api__/v1/content/{self._content_guid}",
                headers=self._headers,
                name="/__api__/v1/content/[guid]",
            )

    @task(3)
    def get_current_user(self) -> None:
        """Fetch the profile of the user identified by the client's API key."""
        self.client.get("/__api__/v1/user", headers=self._headers)

    @task(2)
    def list_users(self) -> None:
        """Fetch the list of registered users."""
        self.client.get("/__api__/v1/users", headers=self._headers)

    @task(1)
    def server_settings(self) -> None:
        """Fetch the server settings endpoint."""
        self.client.get("/__api__/server_settings")


class WorkbenchUser(HttpUser):
    """Simulates a Workbench user checking sessions and server settings.

    Workbench has a thin REST API — most real interaction is via the browser
    UI.  This models the API-accessible actions.
    """

    wait_time = between(1, 3)
    abstract = True

    def on_start(self) -> None:
        """Seed the API key header from the injected load-test credentials."""
        self._api_key = getattr(self.environment, "_vip_credentials", {}).get("api_key", "")
        self._headers = {"Authorization": f"Key {self._api_key}"}

    @task(8)
    def list_sessions(self) -> None:
        """Fetch the list of active Workbench sessions."""
        self.client.get("/api/sessions", headers=self._headers)

    @task(5)
    def server_version(self) -> None:
        """Fetch the Workbench server version."""
        # Workbench's documented version endpoint is /api/version (there is no
        # /api/server/settings — that path 404s). Requires an API token, which
        # on_start sets from the injected credentials.
        self.client.get("/api/version", headers=self._headers)

    @task(1)
    def health_check(self) -> None:
        """Hit the Workbench health-check endpoint."""
        self.client.get("/health-check")


class PackageManagerUser(HttpUser):
    """Simulates Package Manager traffic: repo browsing and package installs.

    Package Manager traffic is heavily read-biased.  The CRAN/PyPI package
    index fetches dominate because every ``install.packages()`` or
    ``pip install`` call hits them.
    """

    wait_time = between(1, 3)
    abstract = True

    def on_start(self) -> None:
        """Seed the auth header and pre-fetch CRAN/PyPI repo names for later tasks."""
        self._token = getattr(self.environment, "_vip_credentials", {}).get("token", "")
        self._headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        # Pre-fetch repo names by type so CRAN tasks hit R repos and PyPI
        # tasks hit Python repos.  Using the wrong repo type causes 404s.
        self._cran_repos: list[str] = []
        self._pypi_repos: list[str] = []
        try:
            resp = self.client.get("/__api__/repos", headers=self._headers)
            if resp.status_code == 200:
                from vip.load_engine import classify_repos

                self._cran_repos, self._pypi_repos = classify_repos(resp.json())
        except Exception:  # noqa: BLE001
            # Best-effort priming — a failed pre-fetch just leaves the repo
            # lists empty; it must not abort the simulated user.
            pass

    @task(3)
    def list_repos(self) -> None:
        """Fetch the list of configured repositories."""
        self.client.get("/__api__/repos", headers=self._headers)

    @task(10)
    def fetch_cran_index(self) -> None:
        """Fetch the CRAN ``PACKAGES`` index of the first repo found by ``on_start``, if any."""
        if self._cran_repos:
            repo = self._cran_repos[0]
            self.client.get(f"/{repo}/latest/src/contrib/PACKAGES")

    @task(5)
    def fetch_pypi_index(self) -> None:
        """Fetch the PyPI simple-index page for numpy from the first repo found, if any."""
        if self._pypi_repos:
            repo = self._pypi_repos[0]
            self.client.get(f"/{repo}/latest/simple/numpy/")

    @task(1)
    def server_status(self) -> None:
        """Fetch the Package Manager status endpoint."""
        self.client.get("/__api__/status")
