"""VIP command-line tools for credential management."""

from __future__ import annotations

import argparse
import json
import sys


def mint_connect_key(args: argparse.Namespace) -> None:
    """Launch interactive browser auth and mint a Connect API key."""
    from vip.auth import start_interactive_auth

    session = start_interactive_auth(args.url)

    if not session.api_key:
        print(json.dumps({"error": "Failed to mint API key"}), file=sys.stderr)
        sys.exit(1)

    # Output JSON with key and key_name for cleanup.
    # The key_name can be used to find the key_id via the API later.
    result = {
        "api_key": session.api_key,
        "key_name": session.key_name,
    }

    print(json.dumps(result))


def main() -> None:
    """Main entry point for the VIP CLI."""
    parser = argparse.ArgumentParser(prog="vip", description="VIP credential tools")
    subparsers = parser.add_subparsers(dest="command")

    # vip auth
    auth_parser = subparsers.add_parser("auth", help="Authentication tools")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")

    # vip auth mint-connect-key
    mint_parser = auth_sub.add_parser(
        "mint-connect-key",
        help="Mint a Connect API key via interactive browser login",
    )
    mint_parser.add_argument("--url", required=True, help="Connect server URL")
    mint_parser.set_defaults(func=mint_connect_key)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
