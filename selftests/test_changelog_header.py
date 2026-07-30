"""Guard the coupling between cliff.toml's header and CHANGELOG.md's top.

``git-cliff --prepend`` only strips the existing header from the file it is
prepending to when the configured ``[changelog] header`` byte-matches the
start of that file. When it does not match, git-cliff prepends its own header
instead of reusing the existing one, and CHANGELOG.md silently grows a second
``# CHANGELOG`` title -- verified against git-cliff 2.13.1.

That makes the header text and the top of CHANGELOG.md a single fact stored in
two files. Editing either alone breaks the next release's changelog, and the
breakage shows up only in the release commit, after the tag is cut. This test
turns that silent failure into a failing check, so a comment is not the only
thing standing between the two copies.

If you need to change the wording at the top of CHANGELOG.md, change
``[changelog] header`` in cliff.toml to match, byte for byte.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Matches src/vip/config.py -- tomllib is stdlib only from 3.11, and CI runs
# selftests on 3.10 as well.
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_cliff_header_is_exact_prefix_of_changelog():
    header = tomllib.loads((REPO_ROOT / "cliff.toml").read_text())["changelog"]["header"]
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text()

    assert changelog.startswith(header), (
        "cliff.toml's [changelog] header must byte-match the start of CHANGELOG.md, "
        "or `git-cliff --prepend` will duplicate the title on the next release.\n"
        f"header starts:    {header[:120]!r}\n"
        f"CHANGELOG starts: {changelog[:120]!r}"
    )
