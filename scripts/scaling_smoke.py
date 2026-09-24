"""Exercise two real API processes, a private worker and gateway with fake voice only."""

import asyncio
import json
import os
import secrets
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


async def exercise(
    compose: list[str], tokens: dict[str, str], process_env: dict[str, str]
) -> dict[str, object]:
    base = "http://127.0.0.1:18081"
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:
        for _ in range(80):
            try:
                if (await client.get("/healthz")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
        else:
            message = "Scaling stack not ready"
            raise RuntimeError(message)

        def headers(user: str, owner: dict[str, str] | None = None) -> dict[str, str]:
            return {
                "Origin": "https://demo.example",
                "Authorization": "Bearer " + tokens[user],
                **({"X-Session-Key": owner["key"]} if owner else {}),
            }

        timings = []
        outcomes: dict[str, int] = {}
        instances: set[str] = set()
        users = list(tokens)[:8]
        for _ in range(3):
            responses = await asyncio.gather(
                *(client.post("/api/sessions", headers=headers(u)) for u in users)
            )
            assert all(r.status_code == 201 for r in responses), [r.status_code for r in responses]
            owners = [r.json() for r in responses]
            instances.update(owner["id"].split("-")[0] for owner in owners)
            assert (await client.post("/api/sessions", headers=headers("extra"))).status_code == 429
            wrong = await client.post(
                "/api/sessions/" + owners[0]["id"] + "/heartbeat",
                headers=headers(users[1], owners[0]),
            )
            assert wrong.status_code == 404

            async def run(user: str, owner: dict[str, str]) -> None:
                started = time.perf_counter()
                path = "/api/sessions/" + owner["id"]
                offered = await client.post(
                    path + "/offer", headers=headers(user, owner), json={"sdp": "v=0\r\n"}
                )
                assert offered.status_code == 200, offered.text
                for _ in range(30):
                    await asyncio.sleep(0.25)
                    response = await client.post(path + "/heartbeat", headers=headers(user, owner))
                    assert response.status_code == 200, response.text
                    status = response.json()["delegation"]
                    if status != "running":
                        assert status in {"completed", "failed", "busy"}, status
                        outcomes[status] = outcomes.get(status, 0) + 1
                        timings.append(time.perf_counter() - started)
                        break
                else:
                    message = "Worker failed to settle within load-test budget"
                    raise RuntimeError(message)
                assert (
                    await client.post(path + "/close", headers=headers(user, owner))
                ).status_code == 200

            await asyncio.gather(*(run(u, o) for u, o in zip(users, owners, strict=True)))
            await asyncio.sleep(2)
        assert instances == {"a", "b"}
        assert outcomes.get("completed", 0) > 0

        # A crash cannot move an existing WebRTC connection. Verify failure isolation and restart.
        crash_owners = []
        for user in ["crash1", "crash2", "crash3", "crash4"]:
            response = await client.post("/api/sessions", headers=headers(user))
            assert response.status_code == 201
            crash_owners.append((user, response.json()))
        a = next((u, o) for u, o in crash_owners if o["id"].startswith("a-"))
        b = next((u, o) for u, o in crash_owners if o["id"].startswith("b-"))
        await asyncio.to_thread(
            subprocess.run,
            [*compose, "kill", "-s", "SIGKILL", "api-a"],
            check=True,
            capture_output=True,
            env=process_env,
        )
        assert (
            await client.post("/api/sessions/" + a[1]["id"] + "/heartbeat", headers=headers(*a))
        ).status_code in {502, 503, 504}
        assert (
            await client.post("/api/sessions/" + b[1]["id"] + "/heartbeat", headers=headers(*b))
        ).status_code == 200
        await asyncio.to_thread(
            subprocess.run,
            [*compose, "start", "api-a"],
            check=True,
            capture_output=True,
            env=process_env,
        )
        for _ in range(40):
            response = await client.post(
                "/api/sessions/" + a[1]["id"] + "/heartbeat", headers=headers(*a)
            )
            if response.status_code == 404:
                break
            await asyncio.sleep(0.25)
        assert response.status_code == 404
        ordered = sorted(timings)
        return {
            "simulated_voice": True,
            "paid_calls": 0,
            "sessions": len(timings),
            "api_instances": sorted(instances),
            "outcomes": outcomes,
            "orchestration_seconds_p50": round(statistics.median(timings), 3),
            "orchestration_seconds_p95": round(ordered[int(0.95 * (len(ordered) - 1))], 3),
            "crash_isolation_and_restart": "passed",
        }


def main() -> None:
    project = "voice-scale-check-" + secrets.token_hex(3)
    tokens = {
        name: secrets.token_urlsafe(32)
        for name in [*(f"u{i}" for i in range(8)), "extra", "crash1", "crash2", "crash3", "crash4"]
    }
    fd, path = tempfile.mkstemp(prefix="voice-scale-", suffix=".env")
    with os.fdopen(fd, "w") as env:
        env.write("VOICE_INVITE_TOKENS=" + json.dumps(tokens) + "\n")
        env.write("VOICE_WORKER_SERVICE_TOKEN=" + secrets.token_urlsafe(32) + "\n")
        env.write(
            "VOICE_DAILY_SESSIONS_PER_USER=100\nVOICE_DAILY_VOICE_SECONDS_PER_USER=30000\nVOICE_DAILY_VOICE_SECONDS_GLOBAL=60000\n"
        )
        env.write("OPENAI_API_KEY=\nVOICE_WORKER_MODE=offline\n")
    compose = [
        "docker",
        "compose",
        "--env-file",
        path,
        "-p",
        project,
        "-f",
        str(ROOT / "deployment/scaling/compose.yaml"),
        "-f",
        str(ROOT / "deployment/scaling/compose.test.yaml"),
    ]
    process_env = {
        k: v for k, v in os.environ.items() if not k.startswith("VOICE_") and k != "OPENAI_API_KEY"
    }
    try:
        subprocess.run([*compose, "up", "-d"], check=True, env=process_env)
        print(json.dumps(asyncio.run(exercise(compose, tokens, process_env)), indent=2))
    finally:
        subprocess.run([*compose, "down", "-v"], check=True, env=process_env)
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
