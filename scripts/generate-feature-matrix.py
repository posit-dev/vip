"""Generate feature matrix JSON — test areas × products cross-tab.

USAGE:
    uv run python scripts/generate-feature-matrix.py [--output PATH]

Derives semantic "test areas" by normalising feature file stems across
categories, then cross-tabulates which products each area covers.  For
cross-cutting categories (cross_product, performance, security, prerequisites)
product coverage is inferred from scenario step text and secondary tags.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vip.gherkin import parse_feature_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "src" / "vip_tests"
DEFAULT_OUTPUT = PROJECT_ROOT / "website" / "src" / "data" / "feature-matrix.json"

PRODUCTS = ["connect", "workbench", "package_manager"]
PRODUCT_LABELS = {
    "connect": "Connect",
    "workbench": "Workbench",
    "package_manager": "Package Manager",
}

# Product-specific categories map 1:1 to a product.
PRODUCT_CATEGORIES = {"connect", "workbench", "package_manager"}
CROSS_CUTTING_CATEGORIES = {"prerequisites", "cross_product", "performance", "security"}

# Human-friendly area names keyed by feature file stem.
AREA_NAMES: dict[str, str] = {
    "test_auth": "Authentication",
    "test_auth_configured": "Auth Configuration",
    "test_auth_policy": "Auth Policy",
    "test_components": "Health Checks",
    "test_concurrency": "Concurrency",
    "test_content_deploy": "Content Deployment",
    "test_data_sources": "Data Sources",
    "test_email": "Email Notifications",
    "test_error_handling": "API Error Handling",
    "test_expected_failure": "Expected Failure Demo",
    "test_https": "HTTPS Enforcement",
    "test_ide_launch": "IDE Launch",
    "test_integration": "Cross-Product Integration",
    "test_login_load_times": "Login Load Times",
    "test_monitoring": "Monitoring & Logging",
    "test_package_install_speed": "Package Install Speed",
    "test_packages": "Package Installation",
    "test_private_repos": "Private Repositories",
    "test_repos": "Package Repositories",
    "test_resource_usage": "Resource Usage",
    "test_resources": "Server Health",
    "test_runtime_versions": "Runtime Versions",
    "test_secrets": "Secret Storage",
    "test_sessions": "Session Lifecycle",
    "test_ssl": "SSL/TLS Certificates",
    "test_users": "User Management",
    "test_versions": "Version Verification",
}

# Regex patterns to detect product mentions in scenario step text.
_PRODUCT_PATTERNS = {
    "connect": re.compile(r"\bConnect\b", re.IGNORECASE),
    "workbench": re.compile(r"\bWorkbench\b", re.IGNORECASE),
    "package_manager": re.compile(r"\bPackage Manager\b", re.IGNORECASE),
}

CATEGORY_LABELS: dict[str, str] = {
    "prerequisites": "Prerequisites",
    "connect": "Connect",
    "workbench": "Workbench",
    "package_manager": "Package Manager",
    "cross_product": "Cross-Product",
    "performance": "Performance",
    "security": "Security",
}


def _area_name(stem: str) -> str:
    if stem in AREA_NAMES:
        return AREA_NAMES[stem]
    return stem.removeprefix("test_").replace("_", " ").title()


def _detect_products_in_steps(scenarios: list[dict]) -> set[str]:
    """Scan scenario steps for product name mentions."""
    products_found: set[str] = set()
    for scenario in scenarios:
        for step in scenario.get("steps", []):
            for product, pattern in _PRODUCT_PATTERNS.items():
                if pattern.search(step):
                    products_found.add(product)
    return products_found


def _read_all_tags(path: Path) -> list[str]:
    """Read ALL file-level tags (not just the first) from a feature file."""
    tags: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("@"):
            for token in stripped.split():
                tags.append(token.lstrip("@"))
        elif stripped.startswith("Feature:"):
            break
    return tags


def generate_matrix(tests_dir: Path, output: Path) -> dict:
    # area_key -> {product -> {scenarios: int, files: [str], conditional: bool}}
    area_data: dict[str, dict[str, dict]] = defaultdict(
        lambda: {p: {"scenarios": 0, "files": [], "conditional": False} for p in PRODUCTS}
    )
    area_categories: dict[str, set[str]] = defaultdict(set)

    for feature_path in sorted(tests_dir.rglob("*.feature")):
        parsed = parse_feature_file(feature_path, relative_to=PROJECT_ROOT)
        rel = feature_path.relative_to(tests_dir)
        category_id = rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        stem = feature_path.stem
        area_key = stem
        scenario_count = len(parsed["scenarios"])
        all_tags = _read_all_tags(feature_path)
        is_conditional = "if_applicable" in all_tags

        area_categories[area_key].add(category_id)

        if category_id in PRODUCT_CATEGORIES:
            # Directly maps to one product.
            product = category_id
            entry = area_data[area_key][product]
            entry["scenarios"] += scenario_count
            entry["files"].append(parsed["file"])
            if is_conditional:
                entry["conditional"] = True
        else:
            # Cross-cutting: detect products from step text and secondary tags.
            products_from_steps = _detect_products_in_steps(parsed["scenarios"])
            products_from_tags = {t for t in all_tags if t in PRODUCT_CATEGORIES}
            detected = products_from_steps | products_from_tags

            # If no specific products detected, assume all three.
            if not detected:
                detected = set(PRODUCTS)

            for product in detected:
                entry = area_data[area_key][product]
                entry["scenarios"] += scenario_count
                entry["files"].append(parsed["file"])
                if is_conditional:
                    entry["conditional"] = True

    # Group areas into product-specific vs cross-cutting for display.
    product_specific_areas = []
    cross_cutting_areas = []

    for area_key in sorted(area_data.keys(), key=lambda k: _area_name(k)):
        cats = area_categories[area_key]
        is_cross_cutting = all(c in CROSS_CUTTING_CATEGORIES for c in cats)

        area_entry = {
            "id": area_key,
            "name": _area_name(area_key),
            "categories": sorted(cats),
            "category_labels": [CATEGORY_LABELS.get(c, c) for c in sorted(cats)],
            "products": {},
        }

        total_scenarios = 0
        for product in PRODUCTS:
            data = area_data[area_key][product]
            covered = data["scenarios"] > 0
            area_entry["products"][product] = {
                "covered": covered,
                "scenario_count": data["scenarios"],
                "conditional": data["conditional"],
                "files": data["files"],
            }
            total_scenarios += data["scenarios"]

        area_entry["total_scenarios"] = total_scenarios

        if is_cross_cutting:
            cross_cutting_areas.append(area_entry)
        else:
            product_specific_areas.append(area_entry)

    # Compute per-product totals.
    product_totals = {}
    for product in PRODUCTS:
        total = sum(
            area["products"][product]["scenario_count"]
            for area in product_specific_areas + cross_cutting_areas
        )
        product_totals[product] = total

    # Not-yet-covered areas (from issue #108).
    not_covered = [
        {"name": "Chronicle", "description": "Not yet available in VIP"},
        {"name": "Flightdeck", "description": "Not yet available in VIP"},
        {"name": "LDAP/SAML/OAuth2 auth flows in CI", "description": "Requires identity provider setup"},
        {"name": "Connect scheduled content", "description": "Planned for future release"},
        {"name": "Workbench HA/multi-node", "description": "Planned for future release"},
        {"name": "Package Manager admin UI", "description": "Planned for future release"},
    ]

    matrix = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "products": [{"id": p, "label": PRODUCT_LABELS[p]} for p in PRODUCTS],
        "product_totals": product_totals,
        "product_specific": product_specific_areas,
        "cross_cutting": cross_cutting_areas,
        "not_covered": not_covered,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    total_areas = len(product_specific_areas) + len(cross_cutting_areas)
    print(f"Wrote {output} ({total_areas} areas)")
    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate VIP feature matrix JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)})",
    )
    args = parser.parse_args()
    generate_matrix(TESTS_DIR, args.output)


if __name__ == "__main__":
    main()
