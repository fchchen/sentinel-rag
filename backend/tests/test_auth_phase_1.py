import time
from uuid import uuid4

import pytest

from tests.helpers import TENANT_A, auth_headers, request


@pytest.mark.anyio
async def test_unauthenticated_request_returns_401() -> None:
    response = await request("GET", "/api/v1/auth/me")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_reader_cannot_delete_document_returns_403() -> None:
    response = await request(
        "DELETE",
        "/api/v1/documents/doc-1",
        headers=auth_headers(roles=["reader"]),
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_can_delete_document() -> None:
    response = await request(
        "DELETE",
        "/api/v1/documents/doc-1",
        headers=auth_headers(roles=["admin"]),
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "document_id": "doc-1"}


@pytest.mark.anyio
async def test_service_account_cannot_access_logs() -> None:
    response = await request(
        "GET",
        "/api/v1/audit/logs",
        headers=auth_headers(roles=["service_account"]),
    )

    assert response.status_code == 403


@pytest.mark.anyio
async def test_tenant_isolation_reader_cannot_see_other_tenant_logs() -> None:
    other_tenant = "22222222-2222-2222-2222-222222222222"
    first_gateway = await request(
        "POST",
        "/api/v1/gateway/complete",
        headers=auth_headers(tenant_id=TENANT_A, roles=["reader"]),
        json_body={
            "prompt": "tenant a request",
            "provider": "auto",
            "max_tokens": 100,
            "context": {"tenant_id": TENANT_A, "app_id": "console", "trace_id": str(uuid4())},
        },
    )
    second_gateway = await request(
        "POST",
        "/api/v1/gateway/complete",
        headers=auth_headers(tenant_id=other_tenant, roles=["reader"]),
        json_body={
            "prompt": "tenant b request",
            "provider": "auto",
            "max_tokens": 100,
            "context": {"tenant_id": other_tenant, "app_id": "console", "trace_id": str(uuid4())},
        },
    )
    response = await request(
        "GET",
        "/api/v1/audit/logs",
        headers=auth_headers(tenant_id=TENANT_A, roles=["reader"]),
    )

    assert first_gateway.status_code == 200
    assert second_gateway.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["count"] == 1
    assert {item["tenant_id"] for item in payload["items"]} == {TENANT_A}


@pytest.mark.anyio
async def test_policy_override_requires_admin_role_and_justification() -> None:
    reader_response = await request(
        "POST",
        "/api/v1/policy/overrides",
        json_body={"rule_id": "policy-1", "justification": "Needed for urgent legal hold"},
        headers=auth_headers(roles=["reader"]),
    )
    admin_missing_justification = await request(
        "POST",
        "/api/v1/policy/overrides",
        json_body={"rule_id": "policy-1", "justification": ""},
        headers=auth_headers(roles=["admin"]),
    )

    assert reader_response.status_code == 403
    assert admin_missing_justification.status_code == 422


@pytest.mark.anyio
async def test_token_expiry_returns_401_not_500() -> None:
    response = await request(
        "GET",
        "/api/v1/auth/me",
        headers=auth_headers(expires_at=int(time.time()) - 10),
    )

    assert response.status_code == 401
