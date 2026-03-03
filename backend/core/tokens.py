import base64
import binascii
import json
import time

from pydantic import BaseModel
from pydantic import ValidationError


class TokenClaims(BaseModel):
    sub: str
    tenant_id: str
    roles: list[str]
    aud: str
    tid: str
    exp: int


def decode_local_token(token: str) -> TokenClaims:
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(f"{token}{padding}".encode("utf-8"))
        payload = json.loads(raw.decode("utf-8"))
        return TokenClaims.model_validate(payload)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise ValueError("Invalid bearer token") from exc


def encode_local_token(
    *,
    subject: str,
    tenant_id: str,
    roles: list[str],
    audience: str,
    tenant: str,
    expires_at: int | None = None,
) -> str:
    payload = {
        "sub": subject,
        "tenant_id": tenant_id,
        "roles": roles,
        "aud": audience,
        "tid": tenant,
        "exp": expires_at or int(time.time()) + 3600,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")
