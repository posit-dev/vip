"""Gherkin feature file parser.

Parses .feature files into structured dicts without any external
Gherkin library — just line-by-line string parsing.
"""

from __future__ import annotations

from pathlib import Path

# Keywords that terminate the feature description block.
_KEYWORDS = frozenset(["Scenario:", "Scenario Outline:", "Background:", "Rule:", "Examples:"])

# Step keywords (prefix match after stripping whitespace).
_STEP_PREFIXES = ("Given ", "When ", "Then ", "And ", "But ")


def parse_feature_file(path: Path, *, relative_to: Path | None = None) -> dict:
    """Parse a ``.feature`` file and return a structured dict.

    Parameters
    ----------
    path:
        Absolute or relative path to the ``.feature`` file.
    relative_to:
        If provided, ``file`` in the returned dict is set relative to this
        directory.  Otherwise the path is returned as-is.

    Returns
    -------
    dict with keys: ``title``, ``description``, ``marker``, ``file``,
    ``scenarios`` (list of dicts with ``title`` and ``steps``).
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    marker = ""
    title = ""
    description_lines: list[str] = []
    scenarios: list[dict] = []

    in_description = False
    current_scenario: dict | None = None

    for raw_line in lines:
        line = raw_line.strip()

        # Skip blank lines and comments.
        if not line or line.startswith("#"):
            continue

        # Tag line — first tag becomes the marker.
        if line.startswith("@"):
            # A tag after we've started collecting scenarios means a new
            # tagged scenario, but we only care about the file-level marker.
            if not marker:
                marker = line.lstrip("@").split()[0] if line.lstrip("@") else ""
            continue

        # Feature title.
        if line.startswith("Feature:"):
            title = line[len("Feature:") :].strip()
            in_description = True
            continue

        # Check if this line starts a new block that ends the description.
        if in_description and any(line.startswith(kw) for kw in _KEYWORDS):
            in_description = False
            # fall through to handle the line below

        if in_description:
            description_lines.append(line)
            continue

        # Scenario / Scenario Outline.
        if line.startswith("Scenario Outline:") or line.startswith("Scenario:"):
            if current_scenario is not None:
                scenarios.append(current_scenario)
            prefix = "Scenario Outline:" if line.startswith("Scenario Outline:") else "Scenario:"
            current_scenario = {
                "title": line[len(prefix) :].strip(),
                "steps": [],
            }
            continue

        # Step lines.
        if current_scenario is not None and any(line.startswith(p) for p in _STEP_PREFIXES):
            current_scenario["steps"].append(line)
            continue

    # Don't forget the last scenario.
    if current_scenario is not None:
        scenarios.append(current_scenario)

    file_str = str(path.relative_to(relative_to)) if relative_to else str(path)

    return {
        "title": title,
        "description": "\n".join(description_lines).strip(),
        "marker": marker,
        "file": file_str,
        "scenarios": scenarios,
    }
