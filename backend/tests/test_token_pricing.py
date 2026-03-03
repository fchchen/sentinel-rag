from core.audit import calculate_invocation_cost


def test_pricing_uses_provider_and_model_specific_rates() -> None:
    cost = calculate_invocation_cost(
        provider="azure_openai",
        model="gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=500,
    )

    assert cost == 0.00045
