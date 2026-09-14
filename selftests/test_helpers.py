"""Selftests for ``src/vip_tests/helpers.py``.

Covers ``pm_url_in_log_lines``, the case-insensitive host/scheme match used
by both ``connect/test_packages.py`` and ``cross_product/test_integration.py``
to confirm a deployment's logs mention the configured Package Manager URL,
and ``pm_url_matches_repo_urls``, the equivalent exact-or-sub-path match used
by ``workbench/test_packages.py`` against R's ``getOption('repos')`` output.
Both share the private ``_split_case_insensitive_prefix`` normalizer. See #619.

Also covers ``extract_repo_urls`` (``vip_tests.workbench.conftest``), the R
console-output URL extraction that feeds ``pm_url_matches_repo_urls`` at that
call site, and its case-insensitive-scheme round trip into that helper.
"""

from __future__ import annotations

from vip_tests.helpers import pm_url_in_log_lines, pm_url_matches_repo_urls
from vip_tests.workbench.conftest import extract_repo_urls


def test_matches_when_host_case_differs():
    # The reported bug: vip.toml says one case, Connect logs another.
    lines = ["Installing from https://PACKAGEmanager01.example.com/cran/latest"]
    assert pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", lines)


def test_matches_when_scheme_case_differs():
    lines = ["source: HTTPS://packagemanager01.example.com/cran/latest"]
    assert pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", lines)


def test_does_not_match_when_only_the_path_case_differs():
    # A URL path IS case-sensitive per RFC 3986. Matching here would trade a
    # false negative for a false positive.
    lines = ["Installing from https://packagemanager01.example.com/CRAN/latest"]
    assert not pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", lines)


def test_does_not_match_a_different_host():
    lines = ["Installing from https://cran.r-project.org/src/contrib"]
    assert not pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", lines)


def test_trailing_slash_on_the_configured_url_is_ignored():
    lines = ["Installing from https://packagemanager01.example.com/cran/latest"]
    assert pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest/", lines)


def test_no_lines_does_not_match():
    assert not pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", [])


def test_does_not_match_when_the_path_is_a_prefix_of_a_longer_token():
    # #657 round 2: "/cran/latest" is a *prefix* of "/cran/latestfoo", not the
    # whole path -- matching here reintroduces the false-positive class the
    # exact-path comparison exists to avoid.
    lines = ["Installing from https://packagemanager01.example.com/cran/latestfoo"]
    assert not pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", lines)


def test_matches_when_a_slash_bounded_sub_path_follows_in_the_log_line():
    # The positive counterpart: a real sub-path, bounded by "/", still matches.
    lines = ["Installing from https://packagemanager01.example.com/cran/latest/src/contrib"]
    assert pm_url_in_log_lines("https://packagemanager01.example.com/cran/latest", lines)


def test_matches_repo_urls_when_host_case_differs():
    urls = ["https://PACKAGEmanager01.example.com/cran/latest"]
    assert pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", urls)


def test_matches_repo_urls_when_scheme_case_differs():
    urls = ["HTTPS://packagemanager01.example.com/cran/latest"]
    assert pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", urls)


def test_matches_repo_urls_does_not_match_when_path_case_differs():
    urls = ["https://packagemanager01.example.com/CRAN/latest"]
    assert not pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", urls)


def test_matches_repo_urls_preserves_sub_path_match():
    # getOption('repos') often reports a more specific sub-path than the
    # configured pm_url (e.g. the CRAN-flavored src/contrib suffix).
    urls = ["https://packagemanager01.example.com/cran/latest/src/contrib"]
    assert pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", urls)


def test_matches_repo_urls_does_not_match_a_similar_but_unrelated_path():
    # "cranfoo" shares the "cran" prefix but is not a sub-path of it -- the
    # "/" boundary is what tells these apart.
    urls = ["https://packagemanager01.example.com/cranfoo"]
    assert not pm_url_matches_repo_urls("https://packagemanager01.example.com/cran", urls)


def test_matches_repo_urls_does_not_match_a_different_host():
    urls = ["https://cran.r-project.org/src/contrib"]
    assert not pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", urls)


def test_matches_repo_urls_no_urls_does_not_match():
    assert not pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", [])


def test_extract_repo_urls_is_case_insensitive_on_scheme():
    # #657 round 2: R can echo the scheme in whatever case repos.conf carries.
    output = '[1] "HTTPS://packagemanager01.example.com/cran/latest"'
    assert extract_repo_urls(output) == ["HTTPS://packagemanager01.example.com/cran/latest"]


def test_extract_repo_urls_feeds_a_mixed_case_scheme_through_to_a_match():
    # Round trip: without IGNORECASE on extraction, this URL would be dropped
    # before pm_url_matches_repo_urls ever saw it, making that helper's own
    # case-insensitive scheme comparison unreachable at this call site.
    output = '[1] "HTTPS://packagemanager01.example.com/cran/latest"'
    urls = extract_repo_urls(output)
    assert pm_url_matches_repo_urls("https://packagemanager01.example.com/cran/latest", urls)
