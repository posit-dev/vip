"""Page objects for Package Manager web UI smoke tests."""

from .ui import (
    Homepage,
    PackageDetailPage,
    PackagesPage,
    open_homepage,
    open_package_detail_via_click,
    open_repo_packages,
    search_packages,
)

__all__ = [
    "Homepage",
    "PackageDetailPage",
    "PackagesPage",
    "open_homepage",
    "open_package_detail_via_click",
    "open_repo_packages",
    "search_packages",
]
