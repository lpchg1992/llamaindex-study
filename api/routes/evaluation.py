"""
RAGAS evaluation endpoints.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from api.schemas import (
    EvalCompareRequest,
    EvalCompareResponse,
    EvalRunRequest,
    EvalRunResponse,
    TestQuestionItem,
)
from rag.eval_storage import init_eval_run_db, init_test_question_db
from rag.evaluation import RAGAS_AVAILABLE, evaluate_ragas
from rag.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/run", response_model=EvalRunResponse)
def run_evaluation(req: EvalRunRequest):
    if not RAGAS_AVAILABLE:
        raise HTTPException(
            status_code=400,
            detail="ragas is not installed. Please install ragas>=0.2.0,<0.3.0 to use evaluation.",
        )

    run_id = f"eval_{uuid.uuid4().hex[:12]}"
    eval_run_db = init_eval_run_db()

    try:
        eval_run_db.create(
            run_id=run_id,
            kb_id=req.kb_id,
            metrics=req.metrics,
            summary={},
            status="running",
        )

        from kb_core.services import QueryRouter

        questions = [{"query": q.query, "reference_answer": q.reference_answer} for q in req.test_questions]
        responses = []
        for q in req.test_questions:
            result = QueryRouter.query_multi(
                kb_ids=[req.kb_id],
                query=q.query,
                top_k=5,
            )
            contexts = []
            if "sources" in result:
                for src in result["sources"]:
                    if isinstance(src, dict) and "text" in src:
                        contexts.append(src["text"])
                    elif hasattr(src, "text"):
                        contexts.append(src.text)
            responses.append({
                "response": result.get("response", ""),
                "contexts": contexts,
            })

        eval_result = evaluate_ragas(
            questions=questions,
            responses=responses,
            metrics=req.metrics,
        )

        updated = eval_run_db.update_result(
            run_id=run_id,
            summary=eval_result,
            status="completed",
        )

        return EvalRunResponse(
            run_id=run_id,
            kb_id=req.kb_id,
            status="completed",
            summary=eval_result.get("summary", {}),
            per_question=eval_result.get("per_question", []),
            created_at=updated["created_at"],
            completed_at=updated.get("completed_at"),
        )

    except Exception as e:
        logger.error(f"Evaluation run {run_id} failed: {type(e).__name__}: {e}", exc_info=True)
        eval_run_db.update_result(
            run_id=run_id,
            summary={},
            status="failed",
            error=f"{type(e).__name__}: {str(e)}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {type(e).__name__}: {str(e)}",
        )


@router.get("/results/{run_id}", response_model=EvalRunResponse)
def get_evaluation_result(run_id: str):
    eval_run_db = init_eval_run_db()
    result = eval_run_db.get(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Evaluation run {run_id} not found")
    return EvalRunResponse(**result)


@router.post("/compare", response_model=EvalCompareResponse)
def compare_evaluations(req: EvalCompareRequest):
    if len(req.run_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 run_ids required for comparison")

    eval_run_db = init_eval_run_db()
    runs = []
    for run_id in req.run_ids:
        result = eval_run_db.get(run_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Evaluation run {run_id} not found")
        runs.append(result)

    comparison = {}
    if req.metric in ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]:
        values = []
        for r in runs:
            summary = r.get("summary", {})
            if req.metric in summary:
                metric_data = summary[req.metric]
                if isinstance(metric_data, dict) and "mean" in metric_data:
                    values.append(metric_data["mean"])
                else:
                    values.append(metric_data)

        if values:
            comparison = {
                "values": values,
                "min": min(values),
                "max": max(values),
                "mean": sum(values) / len(values),
                "best_run_id": runs[values.index(max(values))]["id"] if values else None,
            }

    return EvalCompareResponse(
        metric=req.metric,
        runs=[{"id": r["id"], "kb_id": r["kb_id"], "created_at": r["created_at"]} for r in runs],
        comparison=comparison,
    )


@router.get("/test-questions/{kb_id}", response_model=List[TestQuestionItem])
def get_test_questions(kb_id: str):
    test_question_db = init_test_question_db()
    questions = test_question_db.get_by_kb(kb_id)
    return [TestQuestionItem(query=q["query"], reference_answer=q.get("reference_answer")) for q in questions]


@router.post("/test-questions/{kb_id}")
def add_test_questions(kb_id: str, questions: List[TestQuestionItem]):
    test_question_db = init_test_question_db()
    created = test_question_db.create_batch([
        {"kb_id": kb_id, "query": q.query, "reference_answer": q.reference_answer}
        for q in questions
    ])
    return {"created": created, "kb_id": kb_id}