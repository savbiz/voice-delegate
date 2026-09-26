"""Reject release tags that differ from the installed backend version."""

import os
from importlib.metadata import version


def check_tag(tag: str, package_version: str) -> None:
    expected = f"v{package_version}"
    if tag != expected:
        message = f"Release tag {tag!r} must equal {expected!r}"
        raise ValueError(message)


def main() -> None:
    try:
        check_tag(os.environ["RELEASE_TAG"], version("voice-delegate"))
    except (KeyError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
