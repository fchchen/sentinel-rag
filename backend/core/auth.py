import time
from enum import StrEnum
from typing import Callable, Protocol

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from core.config import settings
from core.tokens import TokenClaims, decode_local_token


class Role(StrEnum):
    READER = "reader"
    ADMIN = "admin"
    SERVICE_ACCOUNT = "service_account"


class AuthContext(BaseModel):
    user_id: str
    tenant_id: str
    roles: list[Role]
    audience: str
    entra_tenant_id: str

    def has_role(self, role: Role) -> bool:
        return role in self.roles


bearer_scheme = HTTPBearer(auto_error=False)


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> TokenClaims: ...


class LocalTokenVerifier:
    async def verify(self, token: str) -> TokenClaims:
        return decode_local_token(token)


class EntraJwtVerifier:
    def __init__(
        self,
        tenant_id: str,
        audience: str,
        issuer: str,
        signing_key: str,
        algorithm: str = "RS256",
    ) -> None:
        self._tenant_id = tenant_id
        self._audience = audience
        self._issuer = issuer
        self._signing_key = signing_key
        self._algorithm = algorithm

    async def verify(self, token: str) -> TokenClaims:
        return self.verify_sync(token)

    def verify_sync(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._signing_key,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
            )
        except jwt.PyJWTError as exc:
            raise ValueError("Invalid bearer token") from exc

        if payload.get("tid") != self._tenant_id:
            raise ValueError("Token tenant mismatch")

        if "tenant_id" not in payload:
            payload["tenant_id"] = payload["tid"]

        return TokenClaims.model_validate(payload)


def _unauthorized(detail: str = "Unauthorized") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _forbidden(detail: str = "Forbidden") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def get_token_verifier() -> TokenVerifier:
    if settings.auth_verifier_mode == "entra":
        if not settings.entra_jwt_signing_key:
            raise _unauthorized("Missing Entra signing key")
        return EntraJwtVerifier(
            tenant_id=settings.entra_tenant_id,
            audience=settings.entra_audience,
            issuer=settings.entra_jwt_issuer,
            signing_key=settings.entra_jwt_signing_key,
            algorithm=settings.entra_jwt_algorithm,
        )
    return LocalTokenVerifier()


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()

    try:
        claims = await verifier.verify(credentials.credentials)
    except ValueError as exc:
        raise _unauthorized("Invalid bearer token") from exc

    if claims.aud != settings.entra_audience or claims.tid != settings.entra_tenant_id:
        raise _unauthorized("Token audience or tenant mismatch")

    if claims.exp <= int(time.time()):
        raise _unauthorized("Token expired")

    return AuthContext(
        user_id=claims.sub,
        tenant_id=claims.tenant_id,
        roles=[Role(role) for role in claims.roles],
        audience=claims.aud,
        entra_tenant_id=claims.tid,
    )


def require_role(role: Role) -> Callable[[AuthContext], AuthContext]:
    async def dependency(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not context.has_role(role):
            raise _forbidden()
        return context

    return dependency


async def require_human_user(context: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if context.has_role(Role.SERVICE_ACCOUNT):
        raise _forbidden()
    return context
