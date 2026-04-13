"""
Core services and data layer for the knowledge base system.
"""

from .services import (
    VectorStoreService,
    ObsidianService,
    ZoteroService,
    GenericService,
    KnowledgeBaseService,
    SearchService,
    QueryRouter,
    TaskService,
    CategoryService,
    AdminService,
    ConsistencyService,
)

__all__ = [
    "VectorStoreService",
    "ObsidianService",
    "ZoteroService",
    "GenericService",
    "KnowledgeBaseService",
    "SearchService",
    "QueryRouter",
    "TaskService",
    "CategoryService",
    "AdminService",
    "ConsistencyService",
]
