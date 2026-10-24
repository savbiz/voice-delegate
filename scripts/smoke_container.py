"""Test an already-built local backend image without provider keys or paid calls."""

import argparse
import json
import logging
import os
import secrets
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

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


def wait_ready(
    client: httpx.Client,
    *,
    budget: float = 25,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Allow the image's 20-second startup grace before declaring readiness failure."""
    deadline = clock() + budget
    while clock() < deadline:
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        sleep(0.2)
    message = "Container not ready within the readiness budget"
    raise SystemExit(message)


def smoke_demo() -> None:
    """Build and exercise the private fake-provider stack and exported worker metrics."""
    root = Path(__file__).resolve().parents[1]
    command = [
        "docker",
        "compose",
        "-p",
        "voice-offline-smoke",
        "-f",
        str(root / "deployment/demo/compose.yaml"),
    ]
    env = dict(os.environ, DEMO_ORIGIN="http://localhost:8080")
    try:
        subprocess.run(
            [*command, "up", "--build", "-d", "--wait", "--wait-timeout", "120"],
            check=True,
            env=env,
        )
        with httpx.Client(base_url="http://127.0.0.1:8080", timeout=3) as client:
            wait_ready(client)
            require("voice-delegate" in client.get("/").text, "Frontend did not load")
            client.headers["Origin"] = "https://untrusted.example"
            require(client.post("/api/sessions").status_code == 403, "Origin guard missing")
            client.headers["Origin"] = "http://localhost:8080"
            owner = client.post("/api/sessions").json()
            path = "/api/sessions/" + owner["id"]
            client.headers["X-Session-Key"] = owner["key"]
            require(
                client.post(path + "/offer", json={"sdp": "v=0\r\n"}).status_code == 200,
                "Fake offer failed",
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                status = client.post(path + "/heartbeat").json()
                if status["delegation"] == "completed" and "4" in status["recap"]["latest_reply"]:
                    break
                time.sleep(0.2)
            else:
                require(False, "Remote offline delegation did not finish")
            require(client.post(path + "/close").json()["finalized"], "Fake close failed")
        with httpx.Client(timeout=3) as client:
            require(
                client.get("http://127.0.0.1:3000/api/health").status_code == 200,
                "Grafana unavailable",
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                response = client.get(
                    "http://127.0.0.1:9090/api/v1/query",
                    params={
                        "query": 'voice_operation_duration_seconds_count{operation="delegate_task"}'
                    },
                )
                if response.status_code == 200 and response.json()["data"]["result"]:
                    break
                time.sleep(1)
            else:
                require(False, "Worker duration metric did not reach Prometheus")
        print("Offline stack smoke passed: frontend, fake voice, worker, metrics; no paid calls.")
    finally:
        cleanup([*command, "down", "--volumes", "--remove-orphans"], env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="voice-delegate:ci")
    parser.add_argument(
        "--demo", action="store_true", help="Build and test the offline compose stack"
    )
    options = parser.parse_args()
    if options.demo:
        smoke_demo()
        return
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
            wait_ready(c)
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
            wait_ready(c)
            require(
                c.post("/api/sessions").status_code == 429,
                'Smoke check failed: c.post("/api/sessions").status_code == 429',
            )
            print("Container smoke checks passed; no paid calls.")
    finally:
        cleanup(["docker", "rm", "-f", name])


if __name__ == "__main__":
    main()
