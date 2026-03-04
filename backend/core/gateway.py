import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import litellm
from redis import Redis
from redis.exceptions import RedisError

from core.config import settings
from core.db import DEFAULT_PROVIDER_CONFIGS, ProviderDefinition, load_provider_configs


class ProviderUnavailableError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        count_toward_breaker: bool = True,
        cooldown_seconds: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.count_toward_breaker = count_toward_breaker
        self.cooldown_seconds = cooldown_seconds


class InvalidProviderRequestError(Exception):
    pass


@dataclass(frozen=True)
class CompletionResult:
    provider: str
    model: str
    completion: str
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class BreakerState:
    failure_timestamps: tuple[float, ...]
    opened_at: float | None
    cooldown_seconds: int

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        return time.time() < self.opened_at + self.cooldown_seconds


class ProviderClient(Protocol):
    def complete(
        self,
        provider: ProviderDefinition,
        prompt: str,
        *,
        max_tokens: int = 1000,
    ) -> CompletionResult: ...


class RedisCircuitBreakerStore:
    def __init__(self, redis_url: str) -> None:
        self._client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.05,
            socket_timeout=0.05,
            retry_on_timeout=False,
        )
        self._fallback: dict[str, BreakerState] = {}

    def get_state(self, provider: str) -> BreakerState:
        try:
            raw = self._client.get(self._key(provider))
            if raw is None:
                return self._fallback.get(provider, BreakerState((), None, 0))
            payload = json.loads(raw)
            return BreakerState(
                failure_timestamps=tuple(payload["failure_timestamps"]),
                opened_at=payload["opened_at"],
                cooldown_seconds=payload["cooldown_seconds"],
            )
        except (RedisError, json.JSONDecodeError, KeyError, TypeError):
            return self._fallback.get(provider, BreakerState((), None, 0))

    def record_success(self, provider: str) -> None:
        state = BreakerState((), None, 0)
        self._write_state(provider, state)

    def record_failure(self, provider: str, *, cooldown_seconds: int) -> BreakerState:
        current = self.get_state(provider)
        now = time.time()
        window_start = now - 60
        failures = tuple(ts for ts in current.failure_timestamps if ts >= window_start) + (now,)
        opened_at = current.opened_at
        applied_cooldown = current.cooldown_seconds

        if len(failures) >= 5:
            opened_at = now
            applied_cooldown = cooldown_seconds

        updated = BreakerState(
            failure_timestamps=failures,
            opened_at=opened_at,
            cooldown_seconds=applied_cooldown,
        )
        self._write_state(provider, updated)
        return updated

    def _key(self, provider: str) -> str:
        return f"sentinel-rag:breaker:{provider}"

    def _write_state(self, provider: str, state: BreakerState) -> None:
        self._fallback[provider] = state
        payload = {
            "failure_timestamps": list(state.failure_timestamps),
            "opened_at": state.opened_at,
            "cooldown_seconds": state.cooldown_seconds,
        }
        ttl = max(state.cooldown_seconds, 60) if state.opened_at is not None else 60
        try:
            self._client.set(self._key(provider), json.dumps(payload), ex=ttl)
        except RedisError:
            return


class StubLLMProviderClient:
    def complete(
        self,
        provider: ProviderDefinition,
        prompt: str,
        *,
        max_tokens: int = 1000,
    ) -> CompletionResult:
        lowered = prompt.lower()

        if "force total failure" in lowered:
            raise ProviderUnavailableError("Forced provider failure")

        if "force azure failure only" in lowered and provider.provider == "azure_openai":
            raise ProviderUnavailableError("Forced azure failure")

        return CompletionResult(
            provider=provider.provider,
            model=provider.model,
            completion=f"stubbed:{provider.provider}:{prompt}",
            prompt_tokens=max(1, len(prompt) // 4 + (1 if len(prompt) % 4 else 0)),
            completion_tokens=max(
                1,
                len(f"stubbed:{provider.provider}:{prompt}") // 4
                + (1 if len(f"stubbed:{provider.provider}:{prompt}") % 4 else 0),
            ),
        )


class LiteLLMProviderClient:
    def __init__(
        self,
        *,
        completion_func: Callable[..., object] | None = None,
    ) -> None:
        self._completion = completion_func or litellm.completion

    def complete(
        self,
        provider: ProviderDefinition,
        prompt: str,
        *,
        max_tokens: int = 1000,
    ) -> CompletionResult:
        kwargs = self._build_request(
            provider=provider,
            prompt=prompt,
            max_tokens=max_tokens,
        )
        try:
            response = self._completion(**kwargs)
        except litellm.RateLimitError as exc:
            raise ProviderUnavailableError(
                f"{provider.provider} rate limited",
                count_toward_breaker=True,
                cooldown_seconds=settings.gateway_rate_limit_cooldown_seconds,
            ) from exc
        except (
            litellm.BadRequestError,
            litellm.AuthenticationError,
            litellm.PermissionDeniedError,
            litellm.NotFoundError,
            litellm.UnprocessableEntityError,
            litellm.ContentPolicyViolationError,
            litellm.ContextWindowExceededError,
            litellm.InvalidRequestError,
        ) as exc:
            raise ProviderUnavailableError(
                f"{provider.provider} rejected request",
                count_toward_breaker=False,
            ) from exc
        except (
            litellm.APIConnectionError,
            litellm.APIError,
            litellm.BadGatewayError,
            litellm.InternalServerError,
            litellm.ServiceUnavailableError,
            litellm.APIResponseValidationError,
        ) as exc:
            raise ProviderUnavailableError(
                f"{provider.provider} request failed",
                count_toward_breaker=True,
            ) from exc
        except Exception as exc:
            raise ProviderUnavailableError(
                f"{provider.provider} request failed",
                count_toward_breaker=True,
            ) from exc

        content = self._extract_text(response)
        if not content:
            raise ProviderUnavailableError(f"{provider.provider} returned an empty completion")

        return CompletionResult(
            provider=provider.provider,
            model=provider.model,
            completion=content,
            prompt_tokens=self._extract_usage(response, "prompt_tokens", prompt),
            completion_tokens=self._extract_usage(response, "completion_tokens", content),
        )

    def _build_request(
        self,
        *,
        provider: ProviderDefinition,
        prompt: str,
        max_tokens: int,
    ) -> dict[str, object]:
        timeout_seconds = provider.timeout_ms / 1000
        base_kwargs: dict[str, object] = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "timeout": timeout_seconds,
        }

        if provider.provider == "azure_openai":
            if not settings.azure_openai_endpoint or not settings.azure_openai_api_key:
                raise ProviderUnavailableError(
                    "azure_openai is not configured",
                    count_toward_breaker=False,
                )
            return {
                **base_kwargs,
                "model": f"azure/{provider.model}",
                "api_base": settings.azure_openai_endpoint,
                "api_key": settings.azure_openai_api_key,
                "api_version": settings.azure_openai_api_version,
            }

        if provider.provider == "openai":
            if not settings.openai_api_key:
                raise ProviderUnavailableError(
                    "openai is not configured",
                    count_toward_breaker=False,
                )
            return {
                **base_kwargs,
                "model": f"openai/{provider.model}",
                "api_key": settings.openai_api_key,
            }

        if provider.provider == "anthropic":
            if not settings.anthropic_api_key:
                raise ProviderUnavailableError(
                    "anthropic is not configured",
                    count_toward_breaker=False,
                )
            return {
                **base_kwargs,
                "model": f"anthropic/{provider.model}",
                "api_key": settings.anthropic_api_key,
            }

        raise ProviderUnavailableError(f"{provider.provider} is not supported")

    def _extract_text(self, response: object) -> str:
        choices = self._get_value(response, "choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        message = self._get_value(first, "message")
        if message is None:
            return ""
        content = self._get_value(message, "content")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                text_value = item.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)
            return "".join(text_parts)
        if isinstance(content, str):
            return content
        return ""

    def _extract_usage(self, response: object, key: str, fallback_text: str) -> int:
        usage = self._get_value(response, "usage")
        if usage is not None:
            value = self._get_value(usage, key)
            if isinstance(value, int) and value > 0:
                return value
        return max(1, len(fallback_text) // 4 + (1 if len(fallback_text) % 4 else 0))

    def _get_value(self, container: object, key: str) -> object | None:
        if isinstance(container, dict):
            return container.get(key)
        return getattr(container, key, None)


class GatewayRouterService:
    def __init__(
        self,
        breaker_store: RedisCircuitBreakerStore,
        provider_client: ProviderClient,
        provider_configs: Sequence[ProviderDefinition] | None = None,
    ) -> None:
        self._breaker_store = breaker_store
        self._provider_client = provider_client
        self._provider_configs = tuple(provider_configs or DEFAULT_PROVIDER_CONFIGS)

    def complete(
        self,
        requested_provider: str,
        prompt: str,
        *,
        max_tokens: int = 1000,
    ) -> CompletionResult:
        providers = self._resolve_candidates(requested_provider)

        explicit_provider = requested_provider != "auto"
        attempted = False
        for provider in providers:
            state = self._breaker_store.get_state(provider.provider)
            if state.is_open:
                continue

            attempted = True
            try:
                result = self._provider_client.complete(
                    provider,
                    prompt,
                    max_tokens=max_tokens,
                )
            except ProviderUnavailableError as exc:
                if exc.count_toward_breaker:
                    cooldown = exc.cooldown_seconds or self._cooldown_seconds(prompt)
                    self._breaker_store.record_failure(provider.provider, cooldown_seconds=cooldown)
                if explicit_provider:
                    raise exc
                continue

            self._breaker_store.record_success(provider.provider)
            return result

        if not attempted and explicit_provider:
            raise ProviderUnavailableError("Provider unavailable")

        raise ProviderUnavailableError("All providers unavailable")

    def _resolve_candidates(self, requested_provider: str) -> Sequence[ProviderDefinition]:
        aliases = {"azure": "azure_openai", "anthropic": "anthropic", "openai": "openai"}

        if requested_provider == "auto":
            return self._provider_configs

        provider_name = aliases.get(requested_provider)
        if provider_name is None:
            raise InvalidProviderRequestError("Unsupported provider")
        return tuple(provider for provider in self._provider_configs if provider.provider == provider_name)

    def _cooldown_seconds(self, prompt: str) -> int:
        if "429" in prompt.lower():
            return settings.gateway_rate_limit_cooldown_seconds
        return settings.gateway_failure_cooldown_seconds


@lru_cache(maxsize=1)
def _build_provider_client() -> ProviderClient:
    if settings.gateway_provider_mode == "stub":
        return StubLLMProviderClient()
    return LiteLLMProviderClient()


@lru_cache(maxsize=1)
def _build_gateway_service() -> GatewayRouterService:
    return GatewayRouterService(
        breaker_store=RedisCircuitBreakerStore(settings.redis_url),
        provider_client=_build_provider_client(),
        provider_configs=load_provider_configs(),
    )


async def get_gateway_service() -> GatewayRouterService:
    return _build_gateway_service()
