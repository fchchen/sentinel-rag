import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError

from core.config import settings
from core.db import DEFAULT_PROVIDER_CONFIGS, ProviderDefinition


class ProviderUnavailableError(Exception):
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
    def complete(self, provider: ProviderDefinition, prompt: str) -> CompletionResult:
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


class GatewayRouterService:
    def __init__(
        self,
        breaker_store: RedisCircuitBreakerStore,
        provider_client: StubLLMProviderClient,
        provider_configs: Sequence[ProviderDefinition] | None = None,
    ) -> None:
        self._breaker_store = breaker_store
        self._provider_client = provider_client
        self._provider_configs = tuple(provider_configs or DEFAULT_PROVIDER_CONFIGS)

    def complete(self, requested_provider: str, prompt: str) -> CompletionResult:
        providers = self._resolve_candidates(requested_provider)

        explicit_provider = requested_provider != "auto"
        attempted = False
        for provider in providers:
            state = self._breaker_store.get_state(provider.provider)
            if state.is_open:
                continue

            attempted = True
            try:
                result = self._provider_client.complete(provider, prompt)
            except ProviderUnavailableError:
                cooldown = self._cooldown_seconds(prompt)
                self._breaker_store.record_failure(provider.provider, cooldown_seconds=cooldown)
                if explicit_provider:
                    raise
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

        provider_name = aliases[requested_provider]
        return tuple(provider for provider in self._provider_configs if provider.provider == provider_name)

    def _cooldown_seconds(self, prompt: str) -> int:
        if "429" in prompt.lower():
            return settings.gateway_rate_limit_cooldown_seconds
        return settings.gateway_failure_cooldown_seconds


@lru_cache(maxsize=1)
def _build_gateway_service() -> GatewayRouterService:
    return GatewayRouterService(
        breaker_store=RedisCircuitBreakerStore(settings.redis_url),
        provider_client=StubLLMProviderClient(),
        provider_configs=DEFAULT_PROVIDER_CONFIGS,
    )


async def get_gateway_service() -> GatewayRouterService:
    return _build_gateway_service()
