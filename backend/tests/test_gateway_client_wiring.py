from types import SimpleNamespace

import httpx
import litellm
import pytest

import core.gateway as gateway_module
from core.config import settings
from core.db import ProviderDefinition
from core.gateway import (
    InvalidProviderRequestError,
    GatewayRouterService,
    LiteLLMProviderClient,
    ProviderUnavailableError,
    RedisCircuitBreakerStore,
    StubLLMProviderClient,
)


def test_litellm_client_builds_azure_request_and_parses_response() -> None:
    captured: dict[str, object] = {}

    def fake_completion(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="real completion"))],
            usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4),
        )

    client = LiteLLMProviderClient(completion_func=fake_completion)
    original_endpoint = settings.azure_openai_endpoint
    original_key = settings.azure_openai_api_key
    original_version = settings.azure_openai_api_version
    settings.azure_openai_endpoint = "https://example.openai.azure.com"
    settings.azure_openai_api_key = "secret"
    settings.azure_openai_api_version = "2024-10-21"
    try:
        result = client.complete(
            ProviderDefinition(
                provider="azure_openai",
                model="gpt-4.1-mini",
                priority=1,
                timeout_ms=12000,
            ),
            "Summarize this",
            max_tokens=321,
        )
    finally:
        settings.azure_openai_endpoint = original_endpoint
        settings.azure_openai_api_key = original_key
        settings.azure_openai_api_version = original_version

    assert result.completion == "real completion"
    assert result.prompt_tokens == 9
    assert result.completion_tokens == 4
    assert captured["model"] == "azure/gpt-4.1-mini"
    assert captured["api_base"] == "https://example.openai.azure.com"
    assert captured["api_key"] == "secret"
    assert captured["api_version"] == "2024-10-21"
    assert captured["max_tokens"] == 321


def test_stub_gateway_rejects_unsupported_provider_alias() -> None:
    client = StubLLMProviderClient()

    service = GatewayRouterService(
        breaker_store=RedisCircuitBreakerStore("redis://localhost:6380/0"),
        provider_client=client,
    )

    with pytest.raises(InvalidProviderRequestError):
        service.complete("gcp", "hello")


def test_default_gateway_builder_loads_provider_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway_module._build_provider_client.cache_clear()
    gateway_module._build_gateway_service.cache_clear()
    monkeypatch.setattr(
        gateway_module,
        "load_provider_configs",
        lambda: (
            ProviderDefinition(
                provider="azure_openai",
                model="custom-model",
                priority=1,
                timeout_ms=12000,
            ),
        ),
    )
    original_mode = settings.gateway_provider_mode
    settings.gateway_provider_mode = "stub"
    try:
        service = gateway_module._build_gateway_service()
    finally:
        settings.gateway_provider_mode = original_mode
        gateway_module._build_provider_client.cache_clear()
        gateway_module._build_gateway_service.cache_clear()

    assert service._provider_configs[0].model == "custom-model"


def test_litellm_rate_limit_error_maps_to_counted_breaker_failure() -> None:
    def fake_completion(**_: object) -> object:
        raise litellm.RateLimitError(
            message="Too many requests",
            llm_provider="azure_openai",
            model="gpt-4.1-mini",
        )

    client = LiteLLMProviderClient(completion_func=fake_completion)
    original_endpoint = settings.azure_openai_endpoint
    original_key = settings.azure_openai_api_key
    settings.azure_openai_endpoint = "https://example.openai.azure.com"
    settings.azure_openai_api_key = "secret"
    try:
        with pytest.raises(ProviderUnavailableError) as exc_info:
            client.complete(
                ProviderDefinition(
                    provider="azure_openai",
                    model="gpt-4.1-mini",
                    priority=1,
                    timeout_ms=12000,
                ),
                "Summarize this",
            )
    finally:
        settings.azure_openai_endpoint = original_endpoint
        settings.azure_openai_api_key = original_key

    assert exc_info.value.count_toward_breaker is True
    assert exc_info.value.cooldown_seconds == settings.gateway_rate_limit_cooldown_seconds


def test_litellm_bad_request_maps_to_non_counted_provider_failure() -> None:
    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(status_code=400, request=request)

    def fake_completion(**_: object) -> object:
        raise litellm.BadRequestError(
            message="Bad request",
            model="gpt-4.1-mini",
            llm_provider="azure_openai",
            response=response,
        )

    client = LiteLLMProviderClient(completion_func=fake_completion)
    original_endpoint = settings.azure_openai_endpoint
    original_key = settings.azure_openai_api_key
    settings.azure_openai_endpoint = "https://example.openai.azure.com"
    settings.azure_openai_api_key = "secret"
    try:
        with pytest.raises(ProviderUnavailableError) as exc_info:
            client.complete(
                ProviderDefinition(
                    provider="azure_openai",
                    model="gpt-4.1-mini",
                    priority=1,
                    timeout_ms=12000,
                ),
                "Summarize this",
            )
    finally:
        settings.azure_openai_endpoint = original_endpoint
        settings.azure_openai_api_key = original_key

    assert exc_info.value.count_toward_breaker is False
    assert exc_info.value.cooldown_seconds is None


def test_non_counted_provider_failures_do_not_open_the_breaker() -> None:
    class RejectingClient:
        def complete(
            self,
            provider: ProviderDefinition,
            prompt: str,
            *,
            max_tokens: int = 1000,
        ) -> object:
            raise ProviderUnavailableError(
                f"{provider.provider} rejected request",
                count_toward_breaker=False,
            )

    provider = ProviderDefinition(
        provider="test-rejecting",
        model="custom-model",
        priority=1,
        timeout_ms=12000,
    )
    breaker_store = RedisCircuitBreakerStore("redis://localhost:6380/0")
    breaker_store.record_success(provider.provider)
    service = GatewayRouterService(
        breaker_store=breaker_store,
        provider_client=RejectingClient(),
        provider_configs=(provider,),
    )

    for _ in range(5):
        with pytest.raises(ProviderUnavailableError):
            service.complete("auto", "hello")

    state = breaker_store.get_state(provider.provider)
    assert state.failure_timestamps == ()
    assert state.opened_at is None


def test_rate_limit_failures_use_longer_cooldown_when_breaker_opens() -> None:
    class RateLimitedClient:
        def complete(
            self,
            provider: ProviderDefinition,
            prompt: str,
            *,
            max_tokens: int = 1000,
        ) -> object:
            raise ProviderUnavailableError(
                f"{provider.provider} rate limited",
                count_toward_breaker=True,
                cooldown_seconds=settings.gateway_rate_limit_cooldown_seconds,
            )

    provider = ProviderDefinition(
        provider="test-rate-limited",
        model="custom-model",
        priority=1,
        timeout_ms=12000,
    )
    breaker_store = RedisCircuitBreakerStore("redis://localhost:6380/0")
    breaker_store.record_success(provider.provider)
    service = GatewayRouterService(
        breaker_store=breaker_store,
        provider_client=RateLimitedClient(),
        provider_configs=(provider,),
    )

    for _ in range(5):
        with pytest.raises(ProviderUnavailableError):
            service.complete("auto", "hello")

    state = breaker_store.get_state(provider.provider)
    assert state.cooldown_seconds == settings.gateway_rate_limit_cooldown_seconds
    assert state.is_open is True
