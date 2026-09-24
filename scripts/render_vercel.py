"""Resolve the public API hostname before Vercel reads its static deployment config."""

import argparse
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LABEL = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"


def render(host: str) -> str:
    if len(host) > 253 or not re.fullmatch(rf"{LABEL}(?:\.{LABEL})*", host):
        message = "API_HOST must be a hostname without scheme, port or path"
        raise ValueError(message)
    template = (ROOT / "frontend/vercel.json").read_text()
    rendered = template.replace("${API_HOST}", host.lower())
    if "${" in rendered:
        message = "Unresolved deployment placeholder"
        raise ValueError(message)
    return json.dumps(json.loads(rendered), indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "frontend/.vercel/vercel.json")
    args = parser.parse_args()
    try:
        content = render(os.environ.get("API_HOST", ""))
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content)
    print(f"Rendered deployment config: {args.output}")


if __name__ == "__main__":
    main()
