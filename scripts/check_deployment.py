"""Keep the sole public API origin in CSP and deployment guides aligned."""

import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path) -> None:
    config = json.loads((root / "frontend/vercel.json").read_text())
    policies = [
        header["value"]
        for route in config["headers"]
        for header in route["headers"]
        if header["key"].lower() == "content-security-policy"
    ]
    if len(policies) != 1:
        message = "Expected one Content-Security-Policy"
        raise ValueError(message)
    directives = [part.split() for part in policies[0].split(";") if part.strip()]
    connections = [part[1:] for part in directives if part[0] == "connect-src"]
    if len(connections) != 1 or len(connections[0]) != 2 or connections[0][0] != "'self'":
        message = "connect-src must permit self and exactly one HTTPS API origin"
        raise ValueError(message)
    origin = urlsplit(connections[0][1])
    if origin.scheme != "https" or not origin.hostname or origin.path or origin.query:
        message = "Expected an HTTPS API origin"
        raise ValueError(message)
    for name in ("deployment/README.md", "frontend/README.md"):
        if origin.hostname not in (root / name).read_text():
            message = f"CSP API host missing from {name}"
            raise ValueError(message)


if __name__ == "__main__":
    check(ROOT)
    print("CSP API host matches deployment documentation.")
