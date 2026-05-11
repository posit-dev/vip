"""Shared helpers for IDE extension validation."""

import re

# Safe extension-ID pattern: publisher.name, e.g. "quarto.quarto" or "ms-python.python".
# Used to validate IDs before interpolating them into CSS selectors.
EXTENSION_ID_RE = re.compile(r"^[\w.-]+$")
