"""
Chat Memory / Chat Engine 模块
"""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ChatMessage:
    role: str
    content: str
    timestamp: str = ""


@dataclass
class ChatSession:
    session_id: str
    kb_id: str
    messages: List[ChatMessage]
    created_at: str
    updated_at: str


class ChatStore:
    def __init__(self, store_dir: Optional[Path] = None):
        if store_dir is None:
            store_dir = Path.home() / ".llamaindex" / "chat_store"
        self._store_dir = store_dir
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: Dict[str, ChatSession] = {}
        self._load_all()

    def _session_file(self, session_id: str) -> Path:
        return self._store_dir / f"{session_id}.json"

    def _load_all(self) -> None:
        for f in self._store_dir.glob("*.json"):
            try:
                import json

                data = json.loads(f.read_text(encoding="utf-8"))
                messages = [ChatMessage(**m) for m in data.get("messages", [])]
                self._sessions[data["session_id"]] = ChatSession(
                    session_id=data["session_id"],
                    kb_id=data["kb_id"],
                    messages=messages,
                    created_at=data["created_at"],
                    updated_at=data["updated_at"],
                )
            except Exception:
                pass

    def _save(self, session: ChatSession) -> None:
        import json
        from datetime import datetime

        session.updated_at = datetime.now().isoformat()
        f = self._session_file(session.session_id)
        f.write_text(json.dumps(asdict(session), ensure_ascii=False), encoding="utf-8")

    def create_session(self, session_id: str, kb_id: str) -> ChatSession:
        from datetime import datetime

        now = datetime.now().isoformat()
        session = ChatSession(
            session_id=session_id,
            kb_id=kb_id,
            messages=[],
            created_at=now,
            updated_at=now,
        )
        self._sessions[session_id] = session
        self._save(session)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        return self._sessions.get(session_id)

    def add_message(self, session_id: str, role: str, content: str) -> ChatSession:
        from datetime import datetime

        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        message = ChatMessage(
            role=role, content=content, timestamp=datetime.now().isoformat()
        )
        session.messages.append(message)
        self._save(session)
        return session

    def get_history(self, session_id: str, limit: int = 10) -> List[ChatMessage]:
        session = self._sessions.get(session_id)
        if not session:
            return []
        return session.messages[-limit:]

    def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            f = self._session_file(session_id)
            if f.exists():
                f.unlink()
            return True
        return False

    def list_sessions(self, kb_id: Optional[str] = None) -> List[ChatSession]:
        sessions = list(self._sessions.values())
        if kb_id:
            sessions = [s for s in sessions if s.kb_id == kb_id]
        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)


class ChatService:
    def __init__(self, chat_store: Optional[ChatStore] = None):
        self._chat_store = chat_store or ChatStore()

    def create_chat_session(
        self, kb_id: str, session_id: Optional[str] = None
    ) -> ChatSession:
        if session_id is None:
            import uuid

            session_id = str(uuid.uuid4())[:8]
        return self._chat_store.create_session(session_id, kb_id)

    def chat(
        self,
        session_id: str,
        message: str,
        kb_id: str,
        query_func: Optional[Any] = None,
    ) -> Dict[str, Any]:
        session = self._chat_store.get_session(session_id)
        if not session:
            session = self.create_chat_session(kb_id, session_id)

        self._chat_store.add_message(session_id, "user", message)

        if query_func:
            response = query_func(message)
        else:
            response = "Chat service requires query_func to be set"

        self._chat_store.add_message(session_id, "assistant", response)

        history = self._chat_store.get_history(session_id, limit=5)
        return {
            "response": response,
            "session_id": session_id,
            "kb_id": kb_id,
            "history": [{"role": m.role, "content": m.content} for m in history],
        }

    def get_session_history(self, session_id: str, limit: int = 10) -> List[Dict]:
        messages = self._chat_store.get_history(session_id, limit)
        return [
            {"role": m.role, "content": m.content, "timestamp": m.timestamp}
            for m in messages
        ]

    def delete_session(self, session_id: str) -> bool:
        return self._chat_store.delete_session(session_id)


_chat_service_instance: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    global _chat_service_instance
    if _chat_service_instance is None:
        _chat_service_instance = ChatService()
    return _chat_service_instance
