"""Tests for capping the resource profiles the capacity scenario auto-detects.

Launching every profile a deployment advertises exhausts a modest host, and a
session that loses that contention fails the scenario for a reason that is not
the deployment's capacity -- the CI nightly failed on a different profile each
run that way (#631).  These cover the pure pieces: parsing a size out of the
dropdown label, and the cap itself.  Selecting profiles in the live dialog
needs a real Workbench and is exercised against a deployment.
"""

from __future__ import annotations

import warnings

import pytest

from vip_tests.workbench.conftest import (
    cap_auto_detected_profiles,
    profile_size_key,
)

# The labels the CI Workbench container advertises, in dropdown order.
CI_PROFILES = [
    "Default (1 CPU, 4GB RAM)",
    "Small (1 CPU, 2GB RAM)",
    "Medium (2 CPUs, 8GB RAM)",
    "Large (4 CPUs, 16GB RAM)",
]


class TestProfileSizeKey:
    def test_orders_the_ci_profiles_smallest_first(self):
        assert sorted(CI_PROFILES, key=profile_size_key) == [
            "Small (1 CPU, 2GB RAM)",
            "Default (1 CPU, 4GB RAM)",
            "Medium (2 CPUs, 8GB RAM)",
            "Large (4 CPUs, 16GB RAM)",
        ]

    def test_cpu_count_dominates_memory(self):
        # 1 CPU / 64GB is still "smaller" than 2 CPUs / 2GB by this key: CPU is
        # the scarcer resource on a CI runner and the tie-break is memory.
        assert profile_size_key("A (1 CPU, 64GB RAM)") < profile_size_key("B (2 CPUs, 2GB RAM)")

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Small (1 CPU, 2GB RAM)", (1.0, 2048.0)),
            ("Medium (2 CPUs, 8GB RAM)", (2.0, 8192.0)),
            ("Tiny (1 vCPU, 512MB RAM)", (1.0, 512.0)),
            ("Frac (0.5 CPU, 1GiB RAM)", (0.5, 1024.0)),
        ],
    )
    def test_parses_cpu_and_memory(self, label, expected):
        assert profile_size_key(label) == expected

    def test_unparseable_label_sorts_last(self):
        # An unknown allocation is the one we least want to launch when capping.
        assert profile_size_key("Bespoke") > profile_size_key("Large (4 CPUs, 16GB RAM)")

    def test_label_without_a_cpu_count_sorts_after_any_that_has_one(self):
        assert profile_size_key("Mem (8GB RAM)") > profile_size_key("Big (99 CPUs, 1GB RAM)")

    def test_labels_without_a_cpu_count_still_order_by_memory(self):
        assert profile_size_key("Mem (8GB RAM)") < profile_size_key("Other (16GB RAM)")

    def test_a_wholly_unparseable_label_sorts_after_a_memory_only_one(self):
        assert profile_size_key("Bespoke") > profile_size_key("Mem (8GB RAM)")


class TestCapAutoDetectedProfiles:
    def test_returns_the_two_smallest_ci_profiles(self):
        # Independent literal, not MAX_AUTO_DETECTED_PROFILES: the point of the
        # assertion is that the default cap is 2, so reading the constant here
        # would pin nothing.
        with pytest.warns(UserWarning):
            assert cap_auto_detected_profiles(CI_PROFILES) == [
                "Small (1 CPU, 2GB RAM)",
                "Default (1 CPU, 4GB RAM)",
            ]

    def test_does_not_warn_or_reorder_when_under_the_limit(self):
        # Under the limit nothing is dropped, so there is nothing to disclose --
        # and the dropdown order is preserved rather than sorted by size.
        names = ["Medium (2 CPUs, 8GB RAM)", "Small (1 CPU, 2GB RAM)"]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert cap_auto_detected_profiles(names, limit=2) == names

    def test_returns_a_copy_so_callers_cannot_mutate_the_input(self):
        names = ["Small (1 CPU, 2GB RAM)"]
        result = cap_auto_detected_profiles(names, limit=4)
        result.append("Large (4 CPUs, 16GB RAM)")
        assert names == ["Small (1 CPU, 2GB RAM)"]

    @pytest.mark.parametrize("limit", [0, -1])
    def test_non_positive_limit_disables_the_cap(self, limit):
        assert cap_auto_detected_profiles(CI_PROFILES, limit=limit) == CI_PROFILES

    def test_warning_names_both_the_chosen_and_the_skipped_profiles(self):
        with pytest.warns(UserWarning) as record:
            cap_auto_detected_profiles(CI_PROFILES, limit=1)
        message = str(record[0].message)
        assert "Small (1 CPU, 2GB RAM)" in message
        assert "skipping" in message
        assert "Large (4 CPUs, 16GB RAM)" in message
        # The escape hatch has to be discoverable from the warning itself.
        assert "workbench.session_profiles" in message

    def test_profile_labels_are_quoted_so_their_own_commas_do_not_run_together(self):
        # "Medium (2 CPUs, 8GB RAM)" contains a comma, so an unquoted join makes
        # the chosen/skipped lists unparseable in the warning.
        with pytest.warns(UserWarning) as record:
            cap_auto_detected_profiles(CI_PROFILES, limit=2)
        message = str(record[0].message)
        assert "'Small (1 CPU, 2GB RAM)', 'Default (1 CPU, 4GB RAM)'" in message
        assert "'Medium (2 CPUs, 8GB RAM)', 'Large (4 CPUs, 16GB RAM)'" in message

    def test_ties_keep_dropdown_order(self):
        # Same allocation, different names: a stable sort must not reshuffle
        # them, so the cap is deterministic across runs.
        names = ["Zeta (1 CPU, 2GB RAM)", "Alpha (1 CPU, 2GB RAM)"]
        with pytest.warns(UserWarning):
            assert cap_auto_detected_profiles(names, limit=1) == ["Zeta (1 CPU, 2GB RAM)"]

    def test_single_profile_is_never_capped(self):
        assert cap_auto_detected_profiles(["Default (1 CPU, 4GB RAM)"]) == [
            "Default (1 CPU, 4GB RAM)"
        ]
