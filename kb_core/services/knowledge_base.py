from pathlib import Path
from typing import List, Optional, Dict, Any

from rag.config import get_settings
from rag.logger import get_logger
from rag.vector_store import LanceDBVectorStore
from kb_core.registry import get_storage_root

logger = get_logger(__name__)

from .vector_store import VectorStoreService

class KnowledgeBaseService:
    """知识库管理服务"""

    @staticmethod
    def list_all() -> List[Dict[str, Any]]:
        """列出所有知识库"""
        from kb_core.registry import registry
        from ..database import init_kb_meta_db, init_document_db

        kbs = registry.list_all()
        kb_meta_db = init_kb_meta_db()
        document_db = init_document_db()
        all_db_rows = {kb["kb_id"]: kb for kb in kb_meta_db.get_all()}
        result = []
        seen: set[str] = set()

        for kb in kbs:
            persist_dir = kb.persist_dir
            exists = persist_dir.exists()

            row_count = 0
            doc_count = 0
            chunk_strategy = None
            if exists:
                try:
                    vs = VectorStoreService.get_vector_store(kb.id)
                    stats = vs.get_stats()
                    row_count = stats.get("row_count", 0)
                    doc_stats = document_db.get_stats(kb.id)
                    doc_count = doc_stats.get("document_count", 0)
                    chunk_strategy = vs.get_chunk_strategy()
                except Exception:
                    pass

            db_row = all_db_rows.get(kb.id, {})
            db_topics = db_row.get("topics", []) or []
            registry_topics = getattr(kb, "topics", []) or []
            all_topics = list(set(db_topics + registry_topics))

            result.append(
                {
                    "id": kb.id,
                    "name": kb.name,
                    "description": kb.description,
                    "source_type": db_row.get("source_type", "unknown"),
                    "status": "indexed" if doc_count > 0 else "empty",
                    "row_count": doc_count,
                    "chunk_count": row_count,
                    "chunk_strategy": chunk_strategy,
                    "topics": all_topics,
                }
            )
            seen.add(kb.id)

        for kb_id, kb_meta in all_db_rows.items():
            if kb_id in seen:
                continue
            persist_dir = Path(
                kb_meta.get("persist_path") or (get_storage_root() / kb_id)
            )
            doc_stats = document_db.get_stats(kb_id)
            doc_count = doc_stats.get("document_count", 0)
            row_count = 0
            info = {
                "id": kb_id,
                "name": kb_meta.get("name", kb_id),
                "description": kb_meta.get("description", ""),
                "source_type": kb_meta.get("source_type", "unknown"),
                "status": "empty",
                "row_count": doc_count,
                "chunk_count": 0,
                "chunk_strategy": None,
                "topics": kb_meta.get("topics", []),
            }
            if persist_dir.exists():
                try:
                    vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
                    stats = vs.get_stats()
                    row_count = stats.get("row_count", 0)
                    info["status"] = "indexed" if doc_count > 0 else "empty"
                    info["chunk_count"] = row_count
                    info["chunk_strategy"] = vs.get_chunk_strategy()
                except Exception:
                    info["status"] = "error"
            result.append(info)

        return result

    @staticmethod
    def get_info(kb_id: str) -> Optional[Dict[str, Any]]:
        """获取知识库详情"""
        from kb_core.registry import registry
        from ..database import init_kb_meta_db

        kb = registry.get(kb_id)
        if kb:
            persist_dir = kb.persist_dir
            info = {
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "persist_dir": str(persist_dir),
            }
        else:
            kb_meta = init_kb_meta_db().get(kb_id)
            if not kb_meta:
                return None
            persist_dir = Path(
                kb_meta.get("persist_path") or (get_storage_root() / kb_id)
            )
            info = {
                "id": kb_id,
                "name": kb_meta.get("name", kb_id),
                "description": kb_meta.get("description", ""),
                "persist_dir": str(persist_dir),
            }

        if persist_dir.exists():
            try:
                vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
                stats = vs.get_stats()
                info["status"] = "indexed" if stats.get("row_count", 0) > 0 else "empty"
                info["row_count"] = stats.get("row_count", 0)
                info["chunk_strategy"] = vs.get_chunk_strategy()
            except Exception:
                info["status"] = "error"
        else:
            info["status"] = "not_found"

        kb_meta = init_kb_meta_db().get(kb_id)
        info["topics"] = kb_meta.get("topics", []) if kb_meta else []
        info["tags"] = kb_meta.get("tags", []) if kb_meta else []

        return info

    @staticmethod
    def get_topics(kb_id: str) -> List[str]:
        """获取知识库的主题关键词
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            主题关键词列表
        """
        from ..database import init_kb_meta_db

        return init_kb_meta_db().get_topics(kb_id)

    @staticmethod
    def refresh_topics(kb_id: str, has_new_docs: bool = True) -> List[str]:
        from kb_analysis.topic_analyzer import analyze_and_update_topics

        return analyze_and_update_topics(kb_id, has_new_docs=has_new_docs)

    @staticmethod
    def update_info(
        kb_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新知识库的基本信息
        
        Args:
            kb_id: 知识库 ID
            name: 新的显示名称（可选）
            description: 新的描述（可选）
            
        Returns:
            更新后的知识库信息
            
        Raises:
            ValueError: 知识库不存在或更新失败
        """
        from kb_core.registry import registry
        from ..database import init_kb_meta_db

        kb_meta_db = init_kb_meta_db()
        success = kb_meta_db.update_info(kb_id, name, description)
        if not success:
            raise ValueError(f"知识库 {kb_id} 不存在或更新失败")

        registry._loaded = False

        return KnowledgeBaseService.get_info(kb_id)

    @staticmethod
    def sync_from_registry(kb_id: str, source_type: str = "obsidian") -> bool:
        """从注册表同步知识库到数据库
        
        将 registry 中的知识库配置同步到数据库的 knowledge_bases 表。
        用于初始化或恢复知识库配置。
        
        Args:
            kb_id: 知识库 ID
            source_type: 来源类型 (obsidian/zotero/generic)
            
        Returns:
            是否成功同步
        """
        from kb_core.registry import registry
        from ..database import init_kb_meta_db

        kb = registry.get(kb_id)
        if not kb:
            return False

        init_kb_meta_db().upsert(
            kb_id=kb.id,
            name=kb.name,
            description=kb.description,
            source_type=source_type,
            persist_path=str(kb.persist_dir),
            tags=kb.tags,
            topics=[],
            source_paths=kb.source_paths,
            source_tags=kb.source_tags,
        )
        return True

    @staticmethod
    def create(
        kb_id: str,
        name: str,
        description: str = "",
        source_type: str = "generic",
    ) -> Dict[str, Any]:
        """创建知识库

        Args:
            kb_id: 知识库唯一标识
            name: 显示名称
            description: 描述
            source_type: 来源类型 (generic, zotero, obsidian, manual)
        """
        from kb_core.registry import registry
        from ..database import init_kb_meta_db

        if registry.exists(kb_id) or init_kb_meta_db().get(kb_id):
            raise ValueError(f"知识库 {kb_id} 已存在")

        persist_dir = VectorStoreService._get_persist_dir_by_source_type(
            kb_id, source_type
        )
        persist_dir.mkdir(parents=True, exist_ok=True)
        init_kb_meta_db().upsert(
            kb_id=kb_id,
            name=name or kb_id,
            description=description,
            source_type=source_type,
            persist_path=str(persist_dir),
        )

        vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
        vs.set_chunk_strategy(get_settings().chunk_strategy)

        return {
            "id": kb_id,
            "name": name,
            "description": description,
            "source_type": source_type,
            "status": "created",
        }

    @staticmethod
    def create_for_zotero(
        kb_id: str,
        name: str,
        description: str = "",
    ) -> Dict[str, Any]:
        """创建 Zotero 类型的知识库
        
        Args:
            kb_id: 知识库 ID
            name: 显示名称
            description: 描述
            
        Returns:
            创建的知识库信息
        """
        return KnowledgeBaseService.create(
            kb_id=kb_id,
            name=name,
            description=description,
            source_type="zotero",
        )

    @staticmethod
    def create_for_obsidian(
        kb_id: str,
        name: str,
        description: str = "",
    ) -> Dict[str, Any]:
        """创建 Obsidian 类型的知识库
        
        Args:
            kb_id: 知识库 ID
            name: 显示名称
            description: 描述
            
        Returns:
            创建的知识库信息
        """
        return KnowledgeBaseService.create(
            kb_id=kb_id,
            name=name,
            description=description,
            source_type="obsidian",
        )

    @staticmethod
    def delete(kb_id: str) -> bool:
        """删除知识库（软删除 + 清理物理数据 + 清理去重状态）

        注意：sync_states 表已废弃，不再清理。
        """
        from kb_core.registry import registry
        from ..database import (
            init_kb_meta_db,
            init_progress_db,
            init_document_db,
            init_chunk_db,
        )
        from sqlalchemy import delete

        info = KnowledgeBaseService.get_info(kb_id)
        if not info:
            return False

        persist_dir = Path(info["persist_dir"])

        vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
        try:
            vs.delete_table()
        except Exception:
            pass

        import shutil

        if persist_dir.exists():
            shutil.rmtree(persist_dir)

        # 清理 SQLite documents 和 chunks
        try:
            doc_db = init_document_db()
            chunk_db = init_chunk_db()

            # 删除该 KB 的所有 chunks
            with chunk_db.db.session_scope() as session:
                from ..database import ChunkModel

                session.execute(delete(ChunkModel).where(ChunkModel.kb_id == kb_id))

            # 删除该 KB 的所有 documents
            with doc_db.db.session_scope() as session:
                from ..database import DocumentModel

                session.execute(
                    delete(DocumentModel).where(DocumentModel.kb_id == kb_id)
                )

            logger.info(
                f"[KnowledgeBaseService.delete] 已清理 KB {kb_id} 的 documents 和 chunks"
            )
        except Exception as e:
            logger.error(
                f"[KnowledgeBaseService.delete] 清理 documents/chunks 失败: {e}"
            )

        init_progress_db().reset(kb_id)

        init_kb_meta_db().set_active(kb_id, is_active=False)

        registry._loaded = False
        registry._bases.clear()

        return True

    @staticmethod
    def initialize(kb_id: str) -> bool:
        """初始化知识库（清空所有数据）
        
        清除向量存储、进度和文档记录，但保留知识库配置。
        用于完全重置知识库到初始状态。
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            是否成功
        """
        from ..database import init_progress_db, init_document_db, init_chunk_db
        from sqlalchemy import delete

        vs = VectorStoreService.get_vector_store(kb_id)
        vs.delete_table()

        # 清理 SQLite documents 和 chunks
        try:
            doc_db = init_document_db()
            chunk_db = init_chunk_db()

            with chunk_db.db.session_scope() as session:
                from ..database import ChunkModel

                session.execute(delete(ChunkModel).where(ChunkModel.kb_id == kb_id))

            with doc_db.db.session_scope() as session:
                from ..database import DocumentModel

                session.execute(
                    delete(DocumentModel).where(DocumentModel.kb_id == kb_id)
                )

            logger.info(
                f"[KnowledgeBaseService.initialize] 已清理 KB {kb_id} 的 documents 和 chunks"
            )
        except Exception as e:
            logger.error(
                f"[KnowledgeBaseService.initialize] 清理 documents/chunks 失败: {e}"
            )

        init_progress_db().reset(kb_id)

        return True

# =============================================================================
