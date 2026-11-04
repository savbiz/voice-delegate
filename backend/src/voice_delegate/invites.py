"""Manage database invitations without a redeploy.

    python -m voice_delegate.invites add NAME     # prints the new code once
    python -m voice_delegate.invites revoke NAME
    python -m voice_delegate.invites list

Codes are stored only as SHA-256 hashes in VOICE_ACCESS_DATABASE (default
.local/access.sqlite3). Use the same name as an existing VOICE_INVITE_TOKENS entry to keep its
quota identity when migrating it. Names starting with "email-" belong to approved requests.
"""

import argparse
import os
import re
import secrets
import sys
from datetime import UTC, datetime

from voice_delegate.access_request import InviteStore

NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m voice_delegate.invites")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("add", "revoke"):
        commands.add_parser(command).add_argument("name")
    commands.add_parser("list")
    args = parser.parse_args(argv)
    store = InviteStore(os.environ.get("VOICE_ACCESS_DATABASE", ".local/access.sqlite3"))
    try:
        if args.command == "list":
            for name, created in store.names():
                stamp = datetime.fromtimestamp(created, UTC).strftime("%Y-%m-%d %H:%M UTC")
                print(f"{name}\t{stamp}")
            return 0
        if args.command == "revoke":
            if store.revoke(args.name):
                print(f"Revoked {args.name}.")
                return 0
            print(f"No invitation named {args.name}.", file=sys.stderr)
            return 1
        if not NAME.fullmatch(args.name) or args.name.startswith("email-"):
            print(
                "Use 1-64 letters, digits, '.', '_' or '-', not starting with email-.",
                file=sys.stderr,
            )
            return 2
        token = secrets.token_urlsafe(32)
        try:
            store.add(args.name, token)
        except ValueError as exc:
            print(f"{exc}; revoke it first to rotate.", file=sys.stderr)
            return 1
        print(token)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
