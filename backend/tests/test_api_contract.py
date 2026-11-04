"""Schemathesis generates edge-case requests from the OpenAPI document and checks every response.

It runs in-process against the fake provider, so it needs no socket and no provider. It asserts
that the API never fails with a server error and that every response, including every error,
matches what the generated documentation promises.
"""

import itertools
from typing import Any

import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis import Case, CheckContext
from schemathesis.checks import not_a_server_error
from schemathesis.core.transport import Response
from schemathesis.specs.openapi.checks import negative_data_rejection, positive_data_acceptance
from voice_delegate.api.app import create_app
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider

SETTINGS = Settings(api_docs=True, trust_proxy=True)
ORIGIN = SETTINGS.allowed_origins[0]
schema = schemathesis.openapi.from_asgi("/openapi.json", create_app(SETTINGS, FakeProvider()))
addresses = itertools.count(1)


def client_address() -> str:
    """A fresh documentation-range address per case, so the per-IP limiter never hides routes."""
    n = next(addresses)
    return f"198.51.{(n // 250) % 250}.{n % 250 + 1}"


@schemathesis.check
def only_503_unavailable(ctx: CheckContext, response: Response, case: Case[Any]) -> None:
    """A 503 is the documented answer for a feature this test leaves unconfigured (feedback,
    access requests); any other 5xx is a crash."""
    if response.status_code >= 500 and response.status_code != 503:
        message = f"unexpected server error {response.status_code}"
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
