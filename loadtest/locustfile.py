"""Locust scenario for the offline demo backend. It never contacts a voice provider.

Run it through ``scripts/loadtest.py``, which starts an isolated backend with the scripted
provider and the offline worker. Pointing this file at a hosted backend would create real
sessions on that server, so the runner refuses any host except the one it started.
"""

import os
import random
import time

from locust import HttpUser, between, task

ORIGIN = os.environ.get("LOADTEST_ORIGIN", "http://localhost:5173")
# Slow enough to be a failure rather than a limit: the offline worker answers in milliseconds.
DELEGATION_TIMEOUT_SECONDS = 20.0
POLL_SECONDS = 0.2
HEARTBEATS_AFTER_RESULT = 3


def client_address() -> str:
    """A distinct documentation-range address per user, so the per-IP limiter sees many clients."""
    return f"198.51.100.{random.randint(1, 254)}"


class VoiceSessionUser(HttpUser):
    """One browser: create a session, connect, wait for the delegated result, then close."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self.client.headers.update({"Origin": ORIGIN, "X-Forwarded-For": client_address()})

    @task
    def conversation(self) -> None:
        with self.client.post("/api/sessions", name="create session", catch_response=True) as made:
            if made.status_code == 429:
                # Capacity shedding is the designed response to overload, not an error.
                made.success()
                self.environment.events.request.fire(
                    request_type="FLOW",
                    name="shed at capacity",
                    response_time=made.elapsed.total_seconds() * 1000,
                    response_length=0,
                    exception=None,
                    context={},
                )
                return
            if made.status_code != 201:
                made.failure(f"unexpected status {made.status_code}")
                return
            owner = made.json()
        path = "/api/sessions/" + owner["id"]
        headers = {"X-Session-Key": owner["key"]}
        try:
            self.client.post(
                path + "/offer", json={"sdp": "v=0\r\n"}, headers=headers, name="connect offer"
            )
            self.await_result(path, headers)
            for _ in range(HEARTBEATS_AFTER_RESULT):
                time.sleep(1.0)
                self.client.post(path + "/heartbeat", headers=headers, name="heartbeat")
        finally:
            self.client.post(path + "/close", headers=headers, name="close session")

    def await_result(self, path: str, headers: dict[str, str]) -> None:
        """Poll like the browser does, and record the time until the spoken-result text exists."""
        started = time.perf_counter()
        error: Exception | None = None
        while time.perf_counter() - started < DELEGATION_TIMEOUT_SECONDS:
            with self.client.post(
                path + "/heartbeat", headers=headers, name="heartbeat", catch_response=True
            ) as beat:
                status = beat.json() if beat.status_code == 200 else {}
            if status.get("delegation") == "completed" and "4" in str(
                status.get("recap", {}).get("latest_reply", "")
            ):
                break
            time.sleep(POLL_SECONDS)
        else:
            error = TimeoutError("delegated result did not arrive")
        self.environment.events.request.fire(
            request_type="FLOW",
            name="delegation result",
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=error,
            context={},
        )
