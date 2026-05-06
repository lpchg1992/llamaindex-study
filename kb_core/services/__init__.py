"""
知识库服务层 - 子模块包

提供统一的业务接口，API 和 CLI 都应该通过这里调用。
所有公开类从此包级别导入，保持向后兼容。
"""

from .vector_store import VectorStoreService
from .obsidian import ObsidianService
from .zotero import ZoteroService
from .generic import GenericService
from .knowledge_base import KnowledgeBaseService
from .search import SearchService
from .query_router import QueryRouter
from .task import TaskService
from .admin import AdminService
from .consistency import ConsistencyService

__all__ = [
    "VectorStoreService",
    "ObsidianService",
    "ZoteroService",
    "GenericService",
    "KnowledgeBaseService",
    "SearchService",
    "QueryRouter",
    "TaskService",
    "AdminService",
    "ConsistencyService",
]
