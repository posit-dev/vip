"""The refusal assertion shared by every access-control scenario here.

Connect and Workbench both evidence 21 CFR 11.10(d) by asking a privileged
endpoint for a response without credentials, and both need to read the answer
the same way. That logic lives in a plain module rather than in either step
file, because importing one pytest-bdd step module from another raises
``IndexError`` -- ``@scenario`` inspects the caller's frame at import time.
A ``conftest.py`` would not work either: ``selftests`` exercises this function
inside a ``pytester`` subprocess that writes its own ``conftest.py``.
"""

import pytest


def assert_refused(status: int) -> None:
    """Assert the control that matters: unauthenticated access is not GRANTED.

    A bare ``in (401, 403)`` check fails a correctly-secured deployment fronted
    by OIDC/SAML or a forward-auth gateway, which answers an unauthenticated
    API call with a redirect (302/307) to a login page rather than a 401/403 --
    a deployment shape VIP explicitly supports. That redirect IS a refusal:
    the request never reached the privileged endpoint unauthenticated.

    So the assertion is inverted: any 2xx is the one outcome that is actually
    unsafe (credentials were not required), and that is what fails the
    scenario. 401/403 and any 3xx are accepted as refusals. Every other status
    is handled explicitly rather than falling through a bare comparison: a 5xx
    means the deployment errored, which is not evidence the access control
    works (or that it's broken) -- it is inconclusive, so the scenario fails
    with a message that says so rather than passing silently. Anything else
    unrecognized also fails explicitly, so a new status code shows up as a
    named failure instead of a silent pass.
    """
    if 200 <= status < 300:
        pytest.fail(
            f"unauthenticated request was granted (status {status}); access control is not enforced"
        )
    if status in (401, 403) or 300 <= status < 400:
        return
    if 500 <= status < 600:
        pytest.fail(
            f"deployment returned {status} for an unauthenticated request; a server "
            "error is not evidence of a working access control"
        )
    pytest.fail(f"unexpected status {status}; cannot confirm the request was refused")
