"""Generate a test catalog JSON file from Gherkin feature files.

USAGE:
    uv run python scripts/generate-test-catalog.py [--output PATH]

Walks ``tests/`` for all ``*.feature`` files, parses them with
``vip.gherkin.parse_feature_file``, groups by category, and writes
a JSON catalog to ``website/src/data/test-catalog.json`` (or the
path given by ``--output``).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from vip.gherkin import parse_feature_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = PROJECT_ROOT / "tests"
DEFAULT_OUTPUT = PROJECT_ROOT / "website" / "src" / "data" / "test-catalog.json"

# Category display labels — underscores become spaces, title-cased.
CATEGORY_LABELS: dict[str, str] = {
    "prerequisites": "Prerequisites",
    "connect": "Connect",
    "workbench": "Workbench",
    "package_manager": "Package Manager",
    "cross_product": "Cross-Product",
    "performance": "Performance",
    "security": "Security",
}


def _label_for(category_id: str) -> str:
    return CATEGORY_LABELS.get(category_id, category_id.replace("_", " ").title())


def generate_catalog(tests_dir: Path, output: Path) -> dict:
    features_by_category: dict[str, list[dict]] = defaultdict(list)

    for feature_path in sorted(tests_dir.rglob("*.feature")):
        parsed = parse_feature_file(feature_path, relative_to=PROJECT_ROOT)
        # Category is the first directory under tests/
        rel = feature_path.relative_to(tests_dir)
        category_id = rel.parts[0] if len(rel.parts) > 1 else "uncategorized"
        features_by_category[category_id].append(parsed)

    # Build sorted category list — prerequisites first, then alphabetical.
    category_ids = sorted(features_by_category.keys())
    if "prerequisites" in category_ids:
        category_ids.remove("prerequisites")
        category_ids.insert(0, "prerequisites")

    categories = []
    for cid in category_ids:
        features = features_by_category[cid]
        scenario_count = sum(len(f["scenarios"]) for f in features)
        categories.append(
            {
                "id": cid,
                "label": _label_for(cid),
                "feature_count": len(features),
                "scenario_count": scenario_count,
                "features": features,
            }
        )

    catalog = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"Wrote {output} ({len(categories)} categories)")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate VIP test catalog JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)})",
    )
    args = parser.parse_args()
    generate_catalog(TESTS_DIR, args.output)


if __name__ == "__main__":
    main()
