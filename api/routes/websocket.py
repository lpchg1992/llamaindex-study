"""
WebSocket and chat endpoints.
"""

from fastapi import APIRouter, WebSocket

from api.schemas import ChatRequest, ChatResponse
from rag.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["websocket"])

# Lazy-init ws_manager — deferred to avoid import-order issues
_ws_manager = None


def _get_ws_manager():
    global _ws_manager
    if _ws_manager is None:
        from kb_core.websocket_manager import ws_manager
        _ws_manager = ws_manager
    return _ws_manager


@router.websocket("/ws/tasks")
async def ws_tasks(websocket: WebSocket):
    try:
        ws = _get_ws_manager()
        await ws.connect(websocket)
    except Exception as e:
        logger.error(f"WebSocket 连接建立失败: {type(e).__name__}: {e}", exc_info=True)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return
    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.debug(f"WebSocket 连接关闭: {e}")
    finally:
        await ws.disconnect(websocket)


@router.post("/chat/{kb_id}", response_model=ChatResponse)
def chat(kb_id: str, req: ChatRequest):
    from rag.chat_engine import get_chat_service
    from kb_core.services import SearchService

    chat_service = get_chat_service()

    def query_func(query: str) -> str:
        result = SearchService.query(
            kb_id=kb_id,
            query=query,
            top_k=5,
        )
        return result.get("response", "")

    session_id = req.session_id or f"chat_{kb_id}"

    result = chat_service.chat(
        session_id=session_id,
        message=req.message,
        kb_id=kb_id,
        query_func=query_func,
    )

    return ChatResponse(**result)


@router.get("/chat/{kb_id}/sessions")
def list_chat_sessions(kb_id: str):
    from rag.chat_engine import get_chat_service

    chat_service = get_chat_service()
    sessions = chat_service.list_sessions(kb_id=kb_id)
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "message_count": len(s.messages),
            }
            for s in sessions
        ]
    }


@router.get("/chat/{kb_id}/history/{session_id}")
def get_chat_history(kb_id: str, session_id: str, limit: int = 10):
    from rag.chat_engine import get_chat_service

    chat_service = get_chat_service()
    history = chat_service.get_session_history(session_id, limit)
    return {"session_id": session_id, "history": history}


@router.delete("/chat/{kb_id}/sessions/{session_id}")
def delete_chat_session(kb_id: str, session_id: str):
    from rag.chat_engine import get_chat_service

    chat_service = get_chat_service()
    success = chat_service.delete_session(session_id)
    return {"deleted": success, "session_id": session_id}