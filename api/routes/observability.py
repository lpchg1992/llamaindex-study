"""
Observability and monitoring endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/stats")
def get_observability_stats(
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
):
    from rag.callbacks import setup_callbacks
    from rag.token_stats_db import get_token_stats_db

    setup_callbacks()

    db = get_token_stats_db()
    vendor_stats = db.get_stats_by_vendor(start_date, end_date)
    total_stats = db.get_total_stats(start_date, end_date)

    return {
        "vendor_stats": vendor_stats,
        "total_calls": total_stats.get("total_calls", 0),
        "total_tokens": total_stats.get("total_tokens", 0),
        "total_prompt_tokens": total_stats.get("total_prompt_tokens", 0),
        "total_completion_tokens": total_stats.get("total_completion_tokens", 0),
        "total_errors": total_stats.get("total_errors", 0),
        "start_date": start_date,
        "end_date": end_date,
    }


@router.post("/reset")
def reset_observability():
    from rag.callbacks import (
        reset_callbacks,
        setup_callbacks,
        reset_model_call_stats,
    )

    setup_callbacks()
    reset_callbacks()
    reset_model_call_stats()
    return {"status": "reset"}


@router.get("/traces")
def get_traces(
    limit: int = Query(100, description="返回条数"),
    start_date: Optional[str] = Query(None, description="开始日期 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期 (YYYY-MM-DD)"),
):
    from rag.callbacks import setup_callbacks, get_rag_stats
    from rag.token_stats_db import get_token_stats_db

    setup_callbacks()

    if start_date or end_date:
        db = get_token_stats_db()
        traces = db.get_trace_events(start_date, end_date, limit)
        return {
            "traces": traces,
            "total": len(traces),
            "start_date": start_date,
            "end_date": end_date,
        }

    rag_stats = get_rag_stats()

    if not rag_stats:
        return {"traces": [], "total": 0}

    traces = rag_stats.trace_events[-limit:]
    return {"traces": traces, "total": len(rag_stats.trace_events)}


@router.get("/dates")
def get_observability_dates():
    from rag.token_stats_db import get_token_stats_db

    db = get_token_stats_db()
    dates = db.get_daily_dates()
    return {"dates": dates}