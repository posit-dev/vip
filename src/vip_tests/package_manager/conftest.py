"""Package Manager test fixtures."""

import pytest

pytestmark = [pytest.mark.package_manager, pytest.mark.xdist_group("package_manager")]
