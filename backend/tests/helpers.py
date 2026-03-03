import base64
import json
import time

import httpx

from main import app

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


def encode_token(
    *,
    subject: str = "user-1",
    tenant_id: str = TENANT_A,
    roles: list[str] | None = None,
    expires_at: int | None = None,
    audience: str = "sentinel-rag-api",
    tenant: str = "local-tenant",
) -> str:
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "roles": roles or ["reader"],
        "aud": audience,
        "tid": tenant,
        "exp": expires_at or int(time.time()) + 3600,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def auth_headers(**kwargs: object) -> dict[str, str]:
    token = encode_token(**kwargs)
    return {"Authorization": f"Bearer {token}"}


async def request(
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=json_body)
