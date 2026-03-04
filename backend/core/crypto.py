import base64
import json
from functools import lru_cache
from hashlib import sha256
from os import urandom

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.types import Text, TypeDecorator

from core.config import settings

_ENVELOPE_PREFIX = "enc:v1:"


class EncryptedText(TypeDecorator[str]):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        if value is None:
            return None
        return get_audit_encryptor().encrypt(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:  # type: ignore[override]
        if value is None:
            return None
        return get_audit_encryptor().decrypt(value)


class AuditEnvelopeEncryptor:
    def __init__(self, key_material: str) -> None:
        self._wrapping_key = sha256(key_material.encode("utf-8")).digest()

    def encrypt(self, plaintext: str) -> str:
        data_key = urandom(32)
        wrapped_key_nonce = urandom(12)
        ciphertext_nonce = urandom(12)

        wrapped_key = AESGCM(self._wrapping_key).encrypt(wrapped_key_nonce, data_key, None)
        ciphertext = AESGCM(data_key).encrypt(ciphertext_nonce, plaintext.encode("utf-8"), None)

        payload = {
            "wk": _encode_bytes(wrapped_key),
            "wkn": _encode_bytes(wrapped_key_nonce),
            "ct": _encode_bytes(ciphertext),
            "ctn": _encode_bytes(ciphertext_nonce),
        }
        return _ENVELOPE_PREFIX + json.dumps(payload, separators=(",", ":"))

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext.startswith(_ENVELOPE_PREFIX):
            return ciphertext

        payload = json.loads(ciphertext[len(_ENVELOPE_PREFIX) :])
        wrapped_key = _decode_bytes(payload["wk"])
        wrapped_key_nonce = _decode_bytes(payload["wkn"])
        encrypted_value = _decode_bytes(payload["ct"])
        ciphertext_nonce = _decode_bytes(payload["ctn"])

        data_key = AESGCM(self._wrapping_key).decrypt(wrapped_key_nonce, wrapped_key, None)
        plaintext = AESGCM(data_key).decrypt(ciphertext_nonce, encrypted_value, None)
        return plaintext.decode("utf-8")


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


@lru_cache(maxsize=1)
def get_audit_encryptor() -> AuditEnvelopeEncryptor:
    return AuditEnvelopeEncryptor(settings.audit_encryption_key)
