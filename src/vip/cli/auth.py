"""``vip auth``: interactive browser auth and Connect API-key minting."""

from __future__ import annotations

import argparse
import json
import sys

from vip.auth import start_interactive_auth


def mint_connect_key(args: argparse.Namespace) -> None:
    """Launch interactive browser auth and mint a Connect API key."""
    session = start_interactive_auth(args.url)

    if not session.api_key:
        # Kept as a direct print+exit rather than raise AuthError: this command's
        # success output is JSON on stdout, so its failure output stays JSON on
        # stderr too instead of the central handler's plain-text "Error: ..." --
        # a script parsing this command's failures expects {"error": "..."}.
        print(json.dumps({"error": "Failed to mint API key"}), file=sys.stderr)
        sys.exit(1)

    result = {
        "api_key": session.api_key,
        "key_name": session.key_name,
    }

    print(json.dumps(result))
