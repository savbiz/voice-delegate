"""Test an already-built local backend image without provider keys or paid calls."""

import json
import secrets
import subprocess
import time

import httpx

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
args += ["voice-delegate:ci"]
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
            raise RuntimeError("container not ready")

        ready()
        c.headers["Origin"] = "https://demo.example"
        assert c.post("/api/sessions").status_code == 401
        c.headers["Authorization"] = "Bearer " + token
        reference = c.post("/api/reference/search", json={"query": "fallback history"})
        assert reference.status_code == 200 and reference.json()["sources"]
        r = c.post("/api/sessions")
        assert r.status_code == 201, r.text
        owner = r.json()
        c.headers["X-Session-Key"] = owner["key"]
        assert c.post("/api/sessions/" + owner["id"] + "/close").status_code == 200
        subprocess.run(["docker", "restart", name], check=True, capture_output=True)
        ready()
        assert c.post("/api/sessions").status_code == 429
        print("Container smoke checks passed; no paid calls.")
finally:
    subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)
