"""
RAG evaluation utilities powered by LlamaIndex built-in evaluators.

Provides:
- Faithfulness evaluation: does the response match retrieved context?
- Relevancy evaluation: are retrieved nodes relevant to the query?
- Correctness evaluation: does the response match a reference answer?
- Batch evaluation runner for bulk assessment.

Evaluators consume LLM tokens. Use sparingly for quality monitoring,
not in the hot query path.

Usage:
    from rag.evaluation import evaluate_response

    result = evaluate_response(query="...", response="...",
                               contexts=[{...}], llm=llm)
    print(result.passing, result.feedback)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from llama_index.core.evaluation import (
    FaithfulnessEvaluator,
    RelevancyEvaluator,
    CorrectnessEvaluator,
    BatchEvalRunner,
)

from rag.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EvalResult:
    """A single evaluation result."""

    passing: bool
    feedback: str
    score: float = 0.0
    pairwise_source: Optional[str] = None


@dataclass
class BatchEvalResult:
    """Aggregated batch evaluation results."""

    total: int = 0
    passing: int = 0
    failing: int = 0
    pass_rate: float = 0.0
    results: List[Dict[str, Any]] = field(default_factory=list)


def evaluate_faithfulness(
    response: str,
    contexts: List[str],
    llm: Any,
) -> EvalResult:
    """Check if the response is faithful to the retrieved contexts."""
    evaluator = FaithfulnessEvaluator(llm=llm)
    result = evaluator.evaluate_response(response=response, contexts=contexts)
    return EvalResult(
        passing=result.passing or False,
        feedback=str(result.feedback or ""),
        score=float(getattr(result, "score", 0.0)),
    )


def evaluate_relevancy(
    query: str,
    contexts: List[str],
    llm: Any,
) -> EvalResult:
    """Check if retrieved contexts are relevant to the query."""
    evaluator = RelevancyEvaluator(llm=llm)
    result = evaluator.evaluate_response(query=query, contexts=contexts)
    return EvalResult(
        passing=result.passing or False,
        feedback=str(result.feedback or ""),
        score=float(getattr(result, "score", 0.0)),
    )


def evaluate_correctness(
    response: str,
    reference_answer: str,
    llm: Any,
) -> EvalResult:
    """Compare the response to a known reference answer."""
    evaluator = CorrectnessEvaluator(llm=llm)
    result = evaluator.evaluate_response(
        response=response,
        reference=reference_answer,
    )
    return EvalResult(
        passing=result.passing or False,
        feedback=str(result.feedback or ""),
        score=float(getattr(result, "score", 0.0)),
    )


def evaluate_full(
    query: str,
    response: str,
    contexts: List[str],
    reference_answer: Optional[str] = None,
    llm: Optional[Any] = None,
) -> Dict[str, EvalResult]:
    """Run all applicable evaluations in one call.

    Args:
        query: Original user query.
        response: Generated answer.
        contexts: Retrieved context strings.
        reference_answer: Optional ground-truth for correctness check.
        llm: LLM instance (created from default config if None).

    Returns:
        Dict with keys "faithfulness", "relevancy", and optionally "correctness".
    """
    if llm is None:
        from rag.ollama_utils import create_llm
        llm = create_llm()

    results: Dict[str, EvalResult] = {}

    if contexts:
        results["faithfulness"] = evaluate_faithfulness(response, contexts, llm)
        results["relevancy"] = evaluate_relevancy(query, contexts, llm)

    if reference_answer:
        results["correctness"] = evaluate_correctness(response, reference_answer, llm)

    return results


def run_batch_evaluation(
    queries: List[str],
    query_engine: Any,
    evaluators: Dict[str, Any],
    llm: Any,
) -> BatchEvalResult:
    runner = BatchEvalRunner(
        evaluators=evaluators,
        workers=2,
        show_progress=True,
    )

    results = runner.evaluate_queries(
        query_engine=query_engine,
        queries=queries,
    )

    all_passing = sum(1 for r in results.values() if r.passing)
    total = len(results)

    return BatchEvalResult(
        total=total,
        passing=all_passing,
        failing=total - all_passing,
        pass_rate=all_passing / total if total > 0 else 0.0,
        results=[
            {
                "query": q,
                "passing": getattr(r, "passing", False),
                "feedback": str(getattr(r, "feedback", "")),
                "score": float(getattr(r, "score", 0.0)),
            }
            for q, r in results.items()
        ],
    )


__all__ = [
    "EvalResult",
    "BatchEvalResult",
    "evaluate_faithfulness",
    "evaluate_relevancy",
    "evaluate_correctness",
    "evaluate_full",
    "run_batch_evaluation",
]
