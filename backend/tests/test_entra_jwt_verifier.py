import time

import jwt

from core.auth import EntraJwtVerifier


def test_entra_jwt_verifier_validates_signed_token() -> None:
    secret = "integration-secret-with-at-least-32-bytes"
    verifier = EntraJwtVerifier(
        tenant_id="tenant-123",
        audience="sentinel-rag-api",
        issuer="https://login.microsoftonline.com/tenant-123/v2.0",
        signing_key=secret,
        algorithm="HS256",
    )
    token = jwt.encode(
        {
            "sub": "entra-user",
            "tenant_id": "tenant-a",
            "roles": ["reader"],
            "aud": "sentinel-rag-api",
            "tid": "tenant-123",
            "iss": "https://login.microsoftonline.com/tenant-123/v2.0",
            "exp": int(time.time()) + 3600,
        },
        secret,
        algorithm="HS256",
    )

    claims = verifier.verify_sync(token)

    assert claims.sub == "entra-user"
    assert claims.tid == "tenant-123"
