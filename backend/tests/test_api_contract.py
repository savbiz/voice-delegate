"""Schemathesis generates edge-case requests from the OpenAPI document and checks every response.

It runs in-process against the fake provider, so it needs no socket and no provider. It asserts
that the API never fails with a server error and that every response, including every error,
matches what the generated documentation promises.
"""

import itertools
import os
from typing import Any

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import Case, CheckContext
from schemathesis.checks import not_a_server_error
from schemathesis.core.transport import Response
from schemathesis.specs.openapi.checks import negative_data_rejection, positive_data_acceptance
from starlette.types import ASGIApp, Receive, Scope, Send
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider


def isolated_settings() -> Settings:
    """Settings built without the developer's VOICE_* variables or .env file."""
    saved = {key: os.environ.pop(key) for key in list(os.environ) if key.startswith("VOICE_")}
    try:
        return Settings(_env_file=None, api_docs=True, trust_proxy=True)  # type: ignore[call-arg]
    finally:
        os.environ.update(saved)


SETTINGS = isolated_settings()
ORIGIN = SETTINGS.allowed_origins[0]


class OneLifespan:
    """Complete the lifespan handshake without running the app's shutdown.

    Schemathesis starts and stops the application around every request. The first shutdown
    would permanently mark the shared session manager as shutting down, and every later
    request would answer 503. That would be the harness failing, not the API.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            await self.app(scope, receive, send)
            return
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


schema = schemathesis.openapi.from_asgi(
    "/openapi.json", OneLifespan(create_app(SETTINGS, FakeProvider()))
)
addresses = itertools.count(1)


def client_address() -> str:
    """A fresh documentation-range address per case, so the per-IP limiter never hides routes."""
    n = next(addresses)
    return f"198.51.{(n // 250) % 250}.{n % 250 + 1}"


# The only operations that may answer 503 here: the feature is switched off in this test's
# configuration, which is the documented behaviour.
UNCONFIGURED = {"/api/feedback", "/api/access-request"}


@schemathesis.check
def only_503_unavailable(ctx: CheckContext, response: Response, case: Case[Any]) -> None:
    """Any 5xx is a crash, except a 503 from an operation whose feature is switched off."""
    if response.status_code < 500:
        return
    if response.status_code == 503 and case.operation.path in UNCONFIGURED:
        return
    message = f"unexpected server error {response.status_code} from {case.operation.path}"
    raise AssertionError(message)


@schema.parametrize()
@settings(
    max_examples=40,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)
def test_every_response_matches_the_documented_contract(case: Case[Any]) -> None:
    case.call_and_validate(
        headers={"Origin": ORIGIN, "X-Forwarded-For": client_address()},
        # Excluded: pydantic deliberately coerces lax input (0 for false) and some schema-valid
        # bodies fail business rules (a disabled adapter), so schema-versus-behaviour symmetry
        # is not a contract here. Response shape and status documentation are.
        excluded_checks=[not_a_server_error, positive_data_acceptance, negative_data_rejection],
        additional_checks=[only_503_unavailable],
    )
