"""Fail unless each given file is a non-empty CycloneDX bill of materials."""

import json
import sys
from pathlib import Path


def check(path: Path) -> str:
    """Return a one-line summary, or raise ValueError describing what is wrong."""
    document = json.loads(path.read_text())
    if document.get("bomFormat") != "CycloneDX":
        message = f"{path}: not a CycloneDX document"
        raise ValueError(message)
    if not document.get("specVersion"):
        message = f"{path}: no specVersion"
        raise ValueError(message)
    components = document.get("components", [])
    if not components:
        message = f"{path}: no components"
        raise ValueError(message)
    unnamed = [item for item in components if not item.get("name") or not item.get("version")]
    if unnamed:
        message = f"{path}: {len(unnamed)} components without a name or version"
        raise ValueError(message)
    untyped = [item for item in components if not item.get("type")]
    if untyped:
        message = f"{path}: {len(untyped)} components without a type"
        raise ValueError(message)
    return f"{path}: CycloneDX {document.get('specVersion')}, {len(components)} components"


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: check_sbom.py FILE...", file=sys.stderr)
        return 2
    try:
        for path in paths:
            print(check(Path(path)))
    except (ValueError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
