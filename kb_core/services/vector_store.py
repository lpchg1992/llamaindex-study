from pathlib import Path

from rag.logger import get_logger
from rag.vector_store import LanceDBVectorStore
from kb_core.registry import get_storage_root

logger = get_logger(__name__)

class VectorStoreService:
    """向量存储服务"""

    @staticmethod
    def _get_persist_dir_by_source_type(kb_id: str, source_type: str) -> Path:
        return get_storage_root() / kb_id

    @staticmethod
    def get_vector_store(kb_id: str) -> LanceDBVectorStore:
        """获取知识库的向量存储"""
        from kb_core.registry import registry

        kb = registry.get(kb_id)
        if kb:
            persist_dir = kb.persist_dir
        else:
            # Registry 中没有，从数据库查询 source_type
            from ..database import init_kb_meta_db

            kb_meta = init_kb_meta_db().get(kb_id)
            if kb_meta:
                source_type = kb_meta.get("source_type", "generic")
            else:
                source_type = "generic"
            persist_dir = VectorStoreService._get_persist_dir_by_source_type(
                kb_id, source_type
            )

        return LanceDBVectorStore(
            persist_dir=persist_dir,
            table_name=kb_id,
        )

    @staticmethod
    def get_persist_dir(kb_id: str) -> Path:
        """获取知识库持久化目录"""
        from kb_core.registry import registry

        kb = registry.get(kb_id)
        if kb:
            return kb.persist_dir

        # Registry 中没有，从数据库查询 source_type
        from ..database import init_kb_meta_db

        kb_meta = init_kb_meta_db().get(kb_id)
        if kb_meta:
            source_type = kb_meta.get("source_type", "generic")
        else:
            source_type = "generic"
        return VectorStoreService._get_persist_dir_by_source_type(kb_id, source_type)

# =============================================================================
