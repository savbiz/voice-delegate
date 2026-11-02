"""Local-only development startup with an isolated, reusable invitation."""

import argparse
import json
import os
import re
import secrets
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def invitation(root: Path) -> str:
    """Publish one owner-only code atomically; never read configured invitation values."""
    directory = root / ".local"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = directory / "dev-invite.txt"
    if not target.exists():
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as temporary:
            temporary.write(secrets.token_urlsafe(32) + "\n")
            temporary.flush()
            candidate = Path(temporary.name)
        try:
            with suppress(FileExistsError):
                os.link(candidate, target)
        finally:
            candidate.unlink()
    if target.is_symlink():
        message = "Invalid local invitation file"
        raise ValueError(message)
    code = target.read_text().strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{43}", code) is None:
        message = "Invalid local invitation file"
        raise ValueError(message)
    target.chmod(0o600)
    return code


def backend_environment(root: Path) -> dict[str, str]:
    """Keep model settings; isolate local auth without rewriting the user's .env."""
    from voice_delegate.config import Settings

    # BaseSettings supports this runtime source override; the mypy plugin omits it.
    settings = Settings(_env_file=root / ".env")  # type: ignore[call-arg]
    if settings.environment != "development" or settings.public_demo:
        message = "Local launcher requires development mode and VOICE_PUBLIC_DEMO=false"
        raise ValueError(message)
    environment = os.environ.copy()
    environment["VOICE_INVITE_TOKENS"] = json.dumps({"local-dev": invitation(root)})
    environment["VOICE_ACCESS_TOKEN"] = ""
    environment["VOICE_ALLOWED_ORIGINS"] = json.dumps(
        list(
            dict.fromkeys(
                [*settings.allowed_origins, "http://127.0.0.1:5173", "http://localhost:5173"]
            )
        )
    )
    environment["VOICE_ALLOWED_HOSTS"] = json.dumps(
        list(dict.fromkeys([*settings.allowed_hosts, "127.0.0.1", "localhost"]))
    )
    return environment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("be", "invite"))
    arguments = parser.parse_args()
    try:
        if arguments.command == "invite":
            # Explicit user action; this is only the generated local code, never a server key.
            print(invitation(ROOT))
            return
        environment = backend_environment(ROOT)
    except (ValueError, OSError):
        print(
            "Local setup unavailable. Check .env, development mode, VOICE_PUBLIC_DEMO=false "
            "and .local directory permissions. No configured credentials were printed.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(
        "Local invitation ready. Run 'make invite' to copy it; existing .env is unchanged.",
        flush=True,
    )
    os.chdir(ROOT)
    os.execvpe(
        "uv",
        [
            "uv",
            "run",
            "uvicorn",
            "voice_delegate.api.app:create_app",
            "--factory",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        environment,
    )


if __name__ == "__main__":
    main()
