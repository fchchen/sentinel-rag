from core.evaluation import PromptBasedEvalJudge
from core.retrieval import RetrievalResultView


def test_judge_version_tracks_prompt_template_name() -> None:
    judge = PromptBasedEvalJudge()

    assert judge.version == "faithfulness_v1"
    assert judge.model == "gpt-4.1-mini"


def test_faithfulness_uses_retrieval_context_not_prompt() -> None:
    judge = PromptBasedEvalJudge()

    prompt = judge.render_prompt(
        completion="Billing invoice summary",
        retrieval_context=(
            RetrievalResultView(
                document_id="doc-1",
                rank=1,
                score=94,
                snippet="Billing invoice reconciliation guide",
            ),
        ),
    )

    assert "Billing invoice reconciliation guide" in prompt
    assert "Billing invoice summary" in prompt
    assert "User prompt" not in prompt
