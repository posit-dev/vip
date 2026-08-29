"""Override points for the Part 11 example.

Redefine these fixtures in your own conftest.py to point the scenarios at the
endpoints your deployment exposes.
"""

import pytest


@pytest.fixture
def privileged_endpoint() -> str:
    """An administrative endpoint that must refuse an unauthenticated caller."""
    return "/__api__/v1/users"
