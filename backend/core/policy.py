import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel

DecisionType = Literal["allow", "block", "allow_with_redactions"]
Severity = Literal["low", "medium", "high", "critical"]

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
INJECTION_PATTERNS = (
    "ignore previous instructions",
    "reveal the system prompt",
    "bypass all policies",
    "developer mode",
    "disregard every guardrail",
)


class PolicyDecision(BaseModel):
    decision: DecisionType
    rule_ids: list[str]
    severity: Severity
    explanations: list[str]
    redacted_prompt: str | None


class PolicyEngine:
    def evaluate(self, prompt: str) -> PolicyDecision:
        lowered = prompt.lower()
        if any(pattern in lowered for pattern in INJECTION_PATTERNS):
            return PolicyDecision(
                decision="block",
                rule_ids=["security:prompt_injection"],
                severity="critical",
                explanations=["Prompt matched the prompt-injection regression corpus."],
                redacted_prompt=self.redact_text(prompt),
            )

        redacted = self.redact_text(prompt)
        if redacted != prompt:
            rule_ids: list[str] = []
            if EMAIL_PATTERN.search(prompt):
                rule_ids.append("pii:email")
            if PHONE_PATTERN.search(prompt):
                rule_ids.append("pii:phone")
            if SSN_PATTERN.search(prompt):
                rule_ids.append("pii:ssn")
            return PolicyDecision(
                decision="allow_with_redactions",
                rule_ids=rule_ids,
                severity="medium",
                explanations=["Prompt contains sensitive data that must be redacted before persistence."],
                redacted_prompt=redacted,
            )

        return PolicyDecision(
            decision="allow",
            rule_ids=[],
            severity="low",
            explanations=[],
            redacted_prompt=None,
        )

    def redact_text(self, text: str) -> str:
        redacted = EMAIL_PATTERN.sub("[REDACTED_EMAIL]", text)
        redacted = PHONE_PATTERN.sub("[REDACTED_PHONE]", redacted)
        redacted = SSN_PATTERN.sub("[REDACTED_SSN]", redacted)
        return redacted

    def redact_for_persistence(self, text: str) -> str:
        return self.redact_text(text)


@lru_cache(maxsize=1)
def _build_policy_engine() -> PolicyEngine:
    return PolicyEngine()


async def get_policy_engine() -> PolicyEngine:
    return _build_policy_engine()
