from functools import lru_cache
from hashlib import sha256
from itertools import zip_longest

from sqlalchemy import func
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from core.db import AuditLog, ModelInvocation, PolicyViolation, get_engine
from core.policy import PolicyDecision


class AuditService:
    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()

    def record_gateway_call(
        self,
        *,
        tenant_id: str,
        app_id: str,
        trace_id: str | None,
        raw_prompt: str,
        decision: PolicyDecision,
        response_redacted: str | None,
        provider: str | None,
        model: str | None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> str:
        redacted_prompt = decision.redacted_prompt or raw_prompt
        prompt_hash = sha256(raw_prompt.encode("utf-8")).hexdigest()

        with Session(self._engine) as session:
            audit_log = AuditLog(
                tenant_id=tenant_id,
                app_id=app_id,
                trace_id=trace_id,
                prompt_hash=prompt_hash,
                redacted_prompt=redacted_prompt,
                response_redacted=response_redacted,
                provider=provider,
                model=model,
                policy_decision=decision.decision,
            )
            session.add(audit_log)
            session.flush()

            for rule_id, explanation in zip_longest(
                decision.rule_ids,
                decision.explanations,
                fillvalue="Policy rule triggered.",
            ):
                session.add(
                    PolicyViolation(
                        audit_log_id=audit_log.id,
                        rule_id=rule_id,
                        severity=decision.severity,
                        explanation=explanation,
                    )
                )

            if provider is not None and model is not None and response_redacted is not None:
                prompt_tokens = prompt_tokens or estimate_tokens(raw_prompt)
                completion_tokens = completion_tokens or estimate_tokens(response_redacted)
                total_tokens = prompt_tokens + completion_tokens
                session.add(
                    ModelInvocation(
                        audit_log_id=audit_log.id,
                        provider=provider,
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        cost_usd=calculate_invocation_cost(
                            provider=provider,
                            model=model,
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                        ),
                    )
                )

            session.commit()
            return audit_log.id

    def cost_summary(self, *, tenant_id: str) -> dict[str, object]:
        with Session(self._engine) as session:
            rows = (
                session.query(ModelInvocation.provider, func.sum(ModelInvocation.cost_usd))
                .join(AuditLog, ModelInvocation.audit_log_id == AuditLog.id)
                .filter(AuditLog.tenant_id == tenant_id)
                .group_by(ModelInvocation.provider)
                .all()
            )
            providers = [
                {"provider": provider, "cost_usd": round(float(cost or 0.0), 6)}
                for provider, cost in rows
            ]
            total_cost = round(sum(item["cost_usd"] for item in providers), 6)
            return {"total_cost_usd": total_cost, "providers": providers}

PRICING_RATES: dict[tuple[str, str], tuple[float, float]] = {
    ("azure_openai", "gpt-4o-mini"): (0.00000015, 0.0000006),
    ("openai", "gpt-4o-mini"): (0.00000015, 0.0000006),
    ("anthropic", "claude-3-5-sonnet"): (0.000003, 0.000015),
}


def estimate_tokens(text: str) -> int:
    from math import ceil

    return max(1, ceil(len(text) / 4))


def calculate_invocation_cost(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    input_rate, output_rate = PRICING_RATES.get((provider, model), (0.000001, 0.000001))
    return round((prompt_tokens * input_rate) + (completion_tokens * output_rate), 6)


@lru_cache(maxsize=1)
def _build_audit_service() -> AuditService:
    return AuditService()


async def get_audit_service() -> AuditService:
    return _build_audit_service()
