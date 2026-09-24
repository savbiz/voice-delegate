"""Probe the local HTTP health route with the deployment's permitted Host header."""

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen


def main() -> int:
    try:
        port = int(os.environ.get("PORT", "8000"))
        hosts = json.loads(os.environ.get("VOICE_ALLOWED_HOSTS", '["localhost"]'))
        host = hosts[0].replace("*", "healthcheck")
        request = Request(f"http://127.0.0.1:{port}/healthz", headers={"Host": host})
        with urlopen(request, timeout=3) as response:
            return 0 if response.status == 200 else 1
    except (URLError, TimeoutError, ValueError, IndexError, TypeError, AttributeError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
