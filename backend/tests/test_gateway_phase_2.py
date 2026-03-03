from uuid import uuid4

import pytest

from tests.helpers import TENANT_A, auth_headers, request


@pytest.mark.anyio
async def test_routes_to_azure_openai_by_default() -> None:
    response = await request(
        "POST",
        "/api/v1/gateway/complete",
        headers=auth_headers(roles=["reader"]),
        json_body={
            "prompt": "Summarize the latest retrieval batch",
            "provider": "auto",
            "max_tokens": 200,
            "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "azure_openai"
    assert payload["model"] == "gpt-4o-mini"
    assert payload["completion"].startswith("stubbed:azure_openai")


@pytest.mark.anyio
async def test_routes_to_anthropic_when_policy_specifies() -> None:
    response = await request(
        "POST",
        "/api/v1/gateway/complete",
        headers=auth_headers(roles=["reader"]),
        json_body={
            "prompt": "Use anthropic for this call",
            "provider": "anthropic",
            "max_tokens": 200,
            "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "anthropic"
    assert payload["model"] == "claude-3-5-sonnet"


@pytest.mark.anyio
async def test_all_providers_fail_raises_503_not_500() -> None:
    response = await request(
        "POST",
        "/api/v1/gateway/complete",
        headers=auth_headers(roles=["reader"]),
        json_body={
            "prompt": "Force total failure",
            "provider": "auto",
            "max_tokens": 200,
            "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
        },
    )

    assert response.status_code == 503


@pytest.mark.anyio
async def test_circuit_breaker_opens_after_5_failures_in_60s_window() -> None:
    for _ in range(5):
        response = await request(
            "POST",
            "/api/v1/gateway/complete",
            headers=auth_headers(roles=["reader"]),
            json_body={
                "prompt": "Force azure failure only",
                "provider": "azure",
                "max_tokens": 200,
                "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
            },
        )
        assert response.status_code == 503

    final_response = await request(
        "POST",
        "/api/v1/gateway/complete",
        headers=auth_headers(roles=["reader"]),
        json_body={
            "prompt": "Normal request after breaker opens",
            "provider": "azure",
            "max_tokens": 200,
            "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
        },
    )

    assert final_response.status_code == 503
    assert final_response.json()["detail"] == "Provider unavailable"
