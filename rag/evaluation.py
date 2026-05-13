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


RAGAS_AVAILABLE = False
RAGAS_IMPORT_ERROR = None
_evaluate = None
_SingleTurnSample = None
_context_precision = None
_context_recall = None
_faithfulness = None
_answer_relevancy = None

try:
    from ragas import evaluate as _evaluate
    from ragas.dataset_schema import SingleTurnSample as _SingleTurnSample
    from ragas.metrics import (
        context_precision as _context_precision,
        context_recall as _context_recall,
        faithfulness as _faithfulness,
        answer_relevancy as _answer_relevancy,
    )

    RAGAS_AVAILABLE = True
except ImportError as e:
    RAGAS_IMPORT_ERROR = str(e)


def evaluate_ragas(
    questions: List[Dict[str, Any]],
    responses: List[Dict[str, Any]],
    metrics: List[str],
    llm: Optional[Any] = None,
) -> Dict[str, Any]:
    if not RAGAS_AVAILABLE:
        raise ImportError(
            f"ragas is not installed or import failed: {RAGAS_IMPORT_ERROR}. "
            "Please install ragas>=0.2.0,<0.3.0 to use evaluate_ragas()."
        )

    supported_metrics = {
        "context_precision": _context_precision,
        "context_recall": _context_recall,
        "faithfulness": _faithfulness,
        "answer_relevancy": _answer_relevancy,
    }

    selected_metrics = []
    for m in metrics:
        if m not in supported_metrics:
            raise ValueError(
                f"Unsupported metric: {m}. Supported: {list(supported_metrics.keys())}"
            )
        selected_metrics.append(supported_metrics[m])

    samples = []
    for q, r in zip(questions, responses):
        sample_data = {
            "user_input": q.get("query", ""),
            "retrieved_contexts": r.get("contexts", []),
            "response": r.get("response", ""),
        }
        if "reference_answer" in q and q["reference_answer"]:
            sample_data["reference"] = q["reference_answer"]
        if "reference_contexts" in r and r["reference_contexts"]:
            sample_data["reference_contexts"] = r["reference_contexts"]
        samples.append(_SingleTurnSample(**sample_data))

    from datasets import Dataset

    dataset = Dataset.from_list(samples)

    result = _evaluate(dataset, metrics=selected_metrics, llm=llm, show_progress=True)

    scores = result.scores
    if hasattr(scores, "to_dict"):
        scores_dict = scores.to_dict()
    elif hasattr(scores, "to_list"):
        scores_dict = [dict(s) for s in scores.to_list()]
    else:
        scores_dict = scores

    score_dicts = []
    for i, score_row in enumerate(scores_dict):
        row = {"question_index": i}
        for metric_name in supported_metrics:
            if metric_name in score_row:
                row[metric_name] = score_row[metric_name]
        score_dicts.append(row)

    summary = {}
    for metric_name in supported_metrics:
        if any(metric_name in sd for sd in score_dicts):
            vals = [sd.get(metric_name, 0) for sd in score_dicts if metric_name in sd]
            if vals:
                summary[metric_name] = {
                    "mean": sum(vals) / len(vals),
                    "min": min(vals),
                    "max": max(vals),
                    "count": len(vals),
                }

    return {
        "summary": summary,
        "per_question": score_dicts,
    }


__all__ = [
    "EvalResult",
    "BatchEvalResult",
    "evaluate_faithfulness",
    "evaluate_relevancy",
    "evaluate_correctness",
    "evaluate_full",
    "run_batch_evaluation",
    "evaluate_ragas",
    "RAGAS_AVAILABLE",
]
