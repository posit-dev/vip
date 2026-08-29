"""Override points for the Part 11 example.

Redefine these fixtures in your own conftest.py to point the scenarios at the
endpoints, repositories and snapshot dates your deployment exposes.
"""

import pytest


@pytest.fixture
def connect_privileged_endpoint() -> str:
    """An administrative Connect endpoint that must refuse an unauthenticated caller."""
    return "/__api__/v1/users"


@pytest.fixture
def workbench_privileged_endpoint() -> str:
    """A Workbench endpoint that must refuse an unauthenticated caller.

    The session API, not ``/health-check`` -- the health endpoint answers
    anonymously by design, so a refusal scenario against it would assert
    nothing about access control.

    Override this if your deployment serves an SPA fallback here. Such a
    deployment answers an anonymous GET with a 200 carrying a login shell, and
    a status-only probe reads that as access granted and fails the scenario.
    An endpoint that answers 401, 403 or a redirect gives the control real
    evidence instead.
    """
    return "/api/sessions"


@pytest.fixture
def validated_repo_name() -> str:
    """The Package Manager repository the validated environment installs from."""
    return "cran"


@pytest.fixture
def validated_snapshot() -> str:
    """A Package Manager snapshot the validated environment pins to.

    A ``YYYY-MM-DD`` date, or the id of a frozen repository URL. Set this to a
    date your repository actually covers: a date before the repository existed
    404s, which the scenario reports as a skip rather than a failure, and a
    skipped scenario still counts as covering its control in the matrix.
    """
    return "2024-01-02"
