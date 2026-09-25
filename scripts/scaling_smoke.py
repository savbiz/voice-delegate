"""Exercise two real API processes, a private worker and gateway with fake voice only."""

import argparse
import asyncio
import json
import logging
import os
import secrets
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


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
            require(
                all(r.status_code == 201 for r in responses), [r.status_code for r in responses]
            )
            owners = [r.json() for r in responses]
            instances.update(owner["id"].split("-")[0] for owner in owners)
            require(
                (await client.post("/api/sessions", headers=headers("extra"))).status_code == 429,
                "Smoke check failed: unexpected session HTTP status",
            )
            wrong = await client.post(
                "/api/sessions/" + owners[0]["id"] + "/heartbeat",
                headers=headers(users[1], owners[0]),
            )
            require(wrong.status_code == 404, "Smoke check failed: wrong.status_code == 404")

            async def run(user: str, owner: dict[str, str]) -> None:
                started = time.perf_counter()
                path = "/api/sessions/" + owner["id"]
                offered = await client.post(
                    path + "/offer", headers=headers(user, owner), json={"sdp": "v=0\r\n"}
                )
                require(offered.status_code == 200, offered.text)
                for _ in range(30):
                    await asyncio.sleep(0.25)
                    response = await client.post(path + "/heartbeat", headers=headers(user, owner))
                    require(response.status_code == 200, response.text)
                    status = response.json()["delegation"]
                    if status != "running":
                        require(status in {"completed", "failed", "busy"}, status)
                        outcomes[status] = outcomes.get(status, 0) + 1
                        timings.append(time.perf_counter() - started)
                        break
                else:
                    message = "Worker failed to settle within load-test budget"
                    raise RuntimeError(message)
                require(
                    (await client.post(path + "/close", headers=headers(user, owner))).status_code
                    == 200,
                    "Smoke check failed: unexpected session HTTP status",
                )

            await asyncio.gather(*(run(u, o) for u, o in zip(users, owners, strict=True)))
            await asyncio.sleep(2)
        require(instances == {"a", "b"}, 'Smoke check failed: instances == {"a", "b"}')
        require(
            outcomes.get("completed", 0) > 0, 'Smoke check failed: outcomes.get("completed", 0) > 0'
        )

        # A crash cannot move an existing WebRTC connection. Verify failure isolation and restart.
        crash_owners = []
        for user in ["crash1", "crash2", "crash3", "crash4"]:
            response = await client.post("/api/sessions", headers=headers(user))
            require(response.status_code == 201, "Smoke check failed: response.status_code == 201")
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
        require(
            (
                await client.post("/api/sessions/" + a[1]["id"] + "/heartbeat", headers=headers(*a))
            ).status_code
            in {502, 503, 504},
            "Smoke check failed: unexpected session HTTP status",
        )
        require(
            (
                await client.post("/api/sessions/" + b[1]["id"] + "/heartbeat", headers=headers(*b))
            ).status_code
            == 200,
            "Smoke check failed: unexpected session HTTP status",
        )
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
        require(response.status_code == 404, "Smoke check failed: response.status_code == 404")
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Use this prebuilt backend image instead of building")
    parser.add_argument("--gateway-image", help="Override the pinned gateway image")
    options = parser.parse_args()
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
    override = Path(path + ".json")
    process_env = {
        k: v for k, v in os.environ.items() if not k.startswith("VOICE_") and k != "OPENAI_API_KEY"
    }
    try:
        if options.image or options.gateway_image:
            rendered = subprocess.run(
                [*compose, "config", "--format", "json"],
                check=True,
                capture_output=True,
                text=True,
                env=process_env,
            )
            config = json.loads(rendered.stdout)
            if options.image:
                for name in ("api-a", "api-b", "worker"):
                    config["services"][name].pop("build", None)
                    config["services"][name]["image"] = options.image
            if options.gateway_image:
                config["services"]["gateway"]["image"] = options.gateway_image
            override.write_text(json.dumps(config))
            compose = [*compose[: compose.index("-f")], "-f", str(override)]
        subprocess.run([*compose, "up", "-d"], check=True, env=process_env)
        print(json.dumps(asyncio.run(exercise(compose, tokens, process_env)), indent=2))
    finally:
        cleanup([*compose, "down", "-v"], env=process_env)
        override.unlink(missing_ok=True)
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
