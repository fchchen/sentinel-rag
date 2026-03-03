import pytest

from tests.helpers import request


@pytest.mark.anyio
async def test_demo_auth_returns_local_token_that_can_call_protected_route() -> None:
    demo_response = await request("POST", "/api/v1/auth/demo")

    assert demo_response.status_code == 200
    payload = demo_response.json()
    assert payload["access_token"]
    assert payload["token_type"] == "Bearer"

    me_response = await request(
        "GET",
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["tenant_id"] == "11111111-1111-1111-1111-111111111111"
