import pytest

from core.auth import LocalTokenVerifier, get_token_verifier
from core.tokens import TokenClaims
from main import app
from tests.helpers import request


@pytest.mark.anyio
async def test_local_token_verifier_can_be_overridden() -> None:
    verifier = LocalTokenVerifier()

    async def override_verifier() -> LocalTokenVerifier:
        return verifier

    async def verify(_: str) -> TokenClaims:
        return TokenClaims(
            sub="override-user",
            tenant_id="tenant-override",
            roles=["admin"],
            aud="sentinel-rag-api",
            tid="local-tenant",
            exp=32503680000,
        )

    verifier.verify = verify  # type: ignore[method-assign]
    app.dependency_overrides[get_token_verifier] = override_verifier

    try:
        response = await request(
            "GET",
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer arbitrary-token"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "override-user"
    assert payload["tenant_id"] == "tenant-override"
