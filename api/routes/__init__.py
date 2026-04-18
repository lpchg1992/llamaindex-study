# Routes Package
from .health import router as health_router
from .tasks import router as tasks_router
from .knowledge_bases import router as kb_router
from .models import router as models_router
from .search import router as search_router
from .ingest import router as ingest_router
from .zotero import router as zotero_router
from .obsidian import router as obsidian_router
from .admin import router as admin_router
from .documents import router as documents_router
from .lance import router as lance_router
from .websocket import router as websocket_router
from .observability import router as observability_router
from .settings import router as settings_router
from .extraction import router as extraction_router

__all__ = [
    "health_router",
    "tasks_router",
    "kb_router",
    "models_router",
    "search_router",
    "ingest_router",
    "zotero_router",
    "obsidian_router",
    "admin_router",
    "documents_router",
    "lance_router",
    "websocket_router",
    "observability_router",
    "settings_router",
    "extraction_router",
]