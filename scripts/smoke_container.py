"""Test an already-built local backend image without provider keys or paid calls."""

import argparse
import json
import logging
import secrets
import subprocess
import time

import httpx


def require(condition: bool, message: object) -> None:
    if not condition:
        raise SystemExit(str(message))


def cleanup(command: list[str], env: dict[str, str] | None = None) -> None:
    try:
        result = subprocess.run(command, check=False, capture_output=True, env=env)
        if result.returncode:
            logging.warning("Smoke teardown failed (exit %s)", result.returncode)
    except OSError:
        logging.warning("Smoke teardown could not run", exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="voice-delegate:ci")
    options = parser.parse_args()
    name = "voice-delegate-check-" + secrets.token_hex(3)
    token = secrets.token_urlsafe(32)
    env = {
        "VOICE_PUBLIC_DEMO": "true",
        "VOICE_ENVIRONMENT": "production",
        "VOICE_ALLOWED_ORIGIN": "https://demo.example",
        "VOICE_ALLOWED_HOSTS": '["127.0.0.1"]',
        "VOICE_INVITE_TOKENS": json.dumps({"tester": token}),
        "VOICE_DAILY_SESSIONS_PER_USER": "1",
    }
    args = ["docker", "run", "-d", "--name", name, "-p", "127.0.0.1:18080:8000"]
    for key, value in env.items():
        args += ["-e", key + "=" + value]
    args += [options.image]
    subprocess.run(args, check=True, capture_output=True)
    try:
        with httpx.Client(base_url="http://127.0.0.1:18080", timeout=2) as c:

            def ready():
                for _ in range(50):
                    try:
                        if c.get("/healthz").status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                message = "container not ready"
                raise RuntimeError(message)

            ready()
            c.headers["Origin"] = "https://demo.example"
            require(
                c.post("/api/sessions").status_code == 401,
                'Smoke check failed: c.post("/api/sessions").status_code == 401',
            )
            c.headers["Authorization"] = "Bearer " + token
            reference = c.post("/api/reference/search", json={"query": "fallback history"})
            require(
                reference.status_code == 200, "Smoke check failed: reference.status_code == 200"
            )
            require(reference.json()["sources"], 'Smoke check failed: reference.json()["sources"]')
            r = c.post("/api/sessions")
            require(r.status_code == 201, r.text)
            owner = r.json()
            c.headers["X-Session-Key"] = owner["key"]
            require(
                c.post("/api/sessions/" + owner["id"] + "/close").status_code == 200,
                "Session close failed",
            )
            subprocess.run(["docker", "restart", name], check=True, capture_output=True)
            ready()
            require(
                c.post("/api/sessions").status_code == 429,
                'Smoke check failed: c.post("/api/sessions").status_code == 429',
            )
            print("Container smoke checks passed; no paid calls.")
    finally:
        cleanup(["docker", "rm", "-f", name])


if __name__ == "__main__":
    main()
