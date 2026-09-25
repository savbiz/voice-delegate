"""Probe the local HTTP health route with the deployment's permitted Host header."""

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(worker: bool = False) -> int:
    try:
        port = 8001 if worker else int(os.environ.get("PORT", "8000"))
        hosts = json.loads(os.environ.get("VOICE_ALLOWED_HOSTS", '["localhost"]'))
        host = hosts[0].replace("*", "healthcheck")
        path = "/jobs" if worker else "/healthz"
        request = Request(
            f"http://127.0.0.1:{port}{path}",
            headers={"Host": host},
            method="POST" if worker else "GET",
        )
        with urlopen(request, timeout=3) as response:
            return 0 if not worker and response.status == 200 else 1
    except HTTPError as error:
        return 0 if worker and error.code == 401 else 1
    except (URLError, TimeoutError, ValueError, IndexError, TypeError, AttributeError):
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    raise SystemExit(main(worker=parser.parse_args().worker))
