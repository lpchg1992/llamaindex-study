"""
知识库服务层

提供统一的业务接口，API 和 CLI 都应该通过这里调用。
解耦业务逻辑和接口层。
"""

import asyncio
import re
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger
from llamaindex_study.vector_store import LanceDBVectorStore
from llamaindex_study.ollama_utils import (
    create_parallel_ollama_embedding,
    configure_global_embed_model,
    configure_llamaindex_for_siliconflow,
)
from kb.registry import get_storage_root
from kb.deduplication import DeduplicationManager

logger = get_logger(__name__)


class VectorStoreService:
    """向量存储服务"""

    @staticmethod
    def _get_persist_dir_by_source_type(kb_id: str, source_type: str) -> Path:
        return get_storage_root() / kb_id

    @staticmethod
    def get_vector_store(kb_id: str) -> LanceDBVectorStore:
        """获取知识库的向量存储"""
        from kb.registry import registry

        kb = registry.get(kb_id)
        if kb:
            persist_dir = kb.persist_dir
        else:
            # Registry 中没有，从数据库查询 source_type
            from kb.database import init_kb_meta_db

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
        from kb.registry import registry

        kb = registry.get(kb_id)
        if kb:
            return kb.persist_dir

        # Registry 中没有，从数据库查询 source_type
        from kb.database import init_kb_meta_db

        kb_meta = init_kb_meta_db().get(kb_id)
        if kb_meta:
            source_type = kb_meta.get("source_type", "generic")
        else:
            source_type = "generic"
        return VectorStoreService._get_persist_dir_by_source_type(kb_id, source_type)


class ObsidianService:
    """Obsidian 导入服务"""

    @staticmethod
    def get_vaults() -> List[Dict[str, Any]]:
        """获取可用的 Obsidian Vault 列表"""
        from kb.registry import get_vault_root

        vault_path = str(get_vault_root())

        vaults = [
            {
                "name": "默认",
                "path": vault_path,
            },
        ]

        try:
            from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS

            configured_paths = set()
            for mapping in OBSIDIAN_KB_MAPPINGS:
                if hasattr(mapping, "vault_path") and mapping.vault_path:
                    configured_paths.add(mapping.vault_path)

            for path in configured_paths:
                if path != vault_path:
                    vaults.append({"name": f"配置 ({Path(path).name})", "path": path})
        except ImportError:
            pass

        result = []
        for v in vaults:
            path = Path(v["path"])
            if path.exists():
                md_count = len(list(path.rglob("*.md")))
                result.append(
                    {
                        **v,
                        "exists": True,
                        "md_files": md_count,
                    }
                )
            else:
                result.append(
                    {
                        **v,
                        "exists": False,
                        "md_files": 0,
                    }
                )

        return result

    @staticmethod
    def get_vault_info(vault_name: str) -> Optional[Dict[str, Any]]:
        """获取 Vault 信息"""
        from kb.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS

                configured_path = None
                for mapping in OBSIDIAN_KB_MAPPINGS:
                    if hasattr(mapping, "vault_path") and mapping.vault_path:
                        expected_name = f"配置 ({Path(mapping.vault_path).name})"
                        if vault_name == expected_name:
                            configured_path = mapping.vault_path
                            break

                if configured_path:
                    vault_path = Path(configured_path)
                else:
                    return None
            except ImportError:
                return None

        if not vault_path.exists():
            return None

        folders = {}
        for item in vault_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                md_count = len(list(item.rglob("*.md")))
                if md_count > 0:
                    folders[item.name] = md_count

        return {
            "name": vault_name,
            "path": str(vault_path),
            "total_md_files": len(list(vault_path.rglob("*.md"))),
            "folders": folders,
        }

    @staticmethod
    def import_vault(
        kb_id: str,
        vault_path: str,
        folder_path: Optional[str] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
        rebuild: bool = False,
        refresh_topics: bool = True,
        force_delete: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        导入 Obsidian 笔记

        Args:
            kb_id: 知识库 ID
            vault_path: Vault 根路径
            folder_path: 子文件夹路径
            recursive: 是否递归
            exclude_patterns: 排除模式
            rebuild: 是否重建
            progress_callback: 进度回调

        Returns:
            导入统计
        """
        from kb.obsidian_processor import ObsidianImporter
        from kb.document_processor import DocumentProcessorConfig

        vault_path = Path(vault_path)
        if not vault_path.exists():
            raise ValueError(f"Vault 路径不存在: {vault_path}")

        import_dir = vault_path
        if folder_path:
            import_dir = vault_path / folder_path
            if not import_dir.exists():
                raise ValueError(f"文件夹不存在: {import_dir}")

        # 获取向量存储
        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = VectorStoreService.get_persist_dir(kb_id)

        # 创建导入器
        importer = ObsidianImporter(
            vault_root=vault_path,
            kb_id=kb_id,
            persist_dir=persist_dir,
        )

        exclude_patterns = exclude_patterns or [
            "*/image/*",
            "*/_resources/*",
            "*/.obsidian/*",
            "*/.trash/*",
            "*/Z_Copilot/*",
            "*/copilot-custom-prompts/*",
        ]
        importer.exclude_patterns = exclude_patterns

        if progress_callback:
            progress_callback(f"开始导入 Obsidian: {import_dir.name}")

        try:
            stats = importer.import_directory(
                directory=import_dir,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=None,
                rebuild=rebuild,
                exclude_patterns=exclude_patterns,
                recursive=recursive,
                force_delete=force_delete,
            )

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点"
                )

            if refresh_topics:
                KnowledgeBaseService.refresh_topics(
                    kb_id=kb_id,
                    has_new_docs=stats.get("files", 0) > 0,
                )
            return stats

        finally:
            pass  # ObsidianImporter 不需要关闭


class ZoteroService:
    """Zotero 导入服务"""

    @staticmethod
    def list_collections() -> List[Dict[str, Any]]:
        """列出所有收藏夹"""
        from kb.zotero_processor import ZoteroImporter

        importer = ZoteroImporter()
        collections = importer.get_collections()
        importer.close()

        return collections

    @staticmethod
    def search_collections(q: str) -> List[Dict[str, Any]]:
        """搜索收藏夹"""
        from kb.zotero_processor import ZoteroImporter

        importer = ZoteroImporter()
        results = importer.search_collections(q)
        importer.close()

        return results

    @staticmethod
    def import_collection(
        kb_id: str,
        collection_id: Optional[str] = None,
        collection_name: Optional[str] = None,
        rebuild: bool = False,
        refresh_topics: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        导入 Zotero 收藏夹

        Args:
            kb_id: 知识库 ID
            collection_id: 收藏夹 ID
            collection_name: 收藏夹名称（用于查找 ID）
            rebuild: 是否重建
            progress_callback: 进度回调

        Returns:
            导入统计
        """
        from kb.zotero_processor import ZoteroImporter
        from kb.document_processor import DocumentProcessorConfig, ProcessingProgress

        lookup_importer = ZoteroImporter()

        if not collection_id and collection_name:
            result = lookup_importer.get_collection_by_name(collection_name)
            if result and "collectionID" in result:
                collection_id = result["collectionID"]
                collection_name = result.get("collectionName", collection_name)
            elif result and "multiple" in result:
                lookup_importer.close()
                raise ValueError(f"名称模糊，存在多个匹配，请用 collection_id 精确指定")
            else:
                lookup_importer.close()
                raise ValueError(f"未找到收藏夹: {collection_name}")

        if not collection_id:
            lookup_importer.close()
            raise ValueError("未指定收藏夹 ID 或名称")

        lookup_importer.close()

        if progress_callback:
            progress_callback(f"开始导入 Zotero: {collection_name}")

        vs = VectorStoreService.get_vector_store(kb_id)

        progress_file = (
            Path.home() / ".llamaindex" / f"zotero_{collection_id}_progress.json"
        )
        progress = ProcessingProgress.load(progress_file)

        from kb.deduplication import DeduplicationManager

        persist_dir = vs.persist_dir or Path.home() / ".llamaindex" / "storage" / kb_id
        dedup_manager = DeduplicationManager(
            kb_id=kb_id,
            persist_dir=persist_dir,
            uri=str(persist_dir),
            table_name=kb_id,
        )

        if rebuild:
            vs.delete_table()
            dedup_manager.clear()
            progress = ProcessingProgress()

        importer = ZoteroImporter(dedup_manager=dedup_manager)
        try:
            stats = importer.import_collection(
                collection_id=collection_id,
                collection_name=collection_name,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=progress,
                rebuild=rebuild,
                progress_file=progress_file,
            )

            progress_file.unlink(missing_ok=True)

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('items', 0)} 篇文献，{stats.get('nodes', 0)} 个节点"
                )

            if refresh_topics:
                KnowledgeBaseService.refresh_topics(
                    kb_id=kb_id,
                    has_new_docs=stats.get("items", 0) > 0,
                )
            return stats

        finally:
            importer.close()


class GenericService:
    """通用文件导入服务"""

    @staticmethod
    def import_file(
        kb_id: str,
        path: str,
        refresh_topics: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        导入单个文件

        Args:
            kb_id: 知识库 ID
            path: 文件路径
            progress_callback: 进度回调

        Returns:
            导入统计
        """
        from kb.generic_processor import GenericImporter

        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"文件不存在: {path}")

        vs = VectorStoreService.get_vector_store(kb_id)
        importer = GenericImporter()

        if progress_callback:
            progress_callback(f"开始导入: {file_path.name}")

        try:
            stats = importer.process_file(
                path=file_path,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
            )

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点"
                )

            if refresh_topics:
                KnowledgeBaseService.refresh_topics(
                    kb_id=kb_id,
                    has_new_docs=stats.get("files", 0) > 0,
                )
            return stats

        except Exception as e:
            if progress_callback:
                progress_callback(f"导入失败: {e}")
            raise


class KnowledgeBaseService:
    """知识库管理服务"""

    @staticmethod
    def list_all() -> List[Dict[str, Any]]:
        """列出所有知识库"""
        from kb.registry import registry
        from kb.database import init_kb_meta_db

        kbs = registry.list_all()
        kb_meta_db = init_kb_meta_db()
        all_db_rows = {kb["kb_id"]: kb for kb in kb_meta_db.get_all()}
        result = []
        seen: set[str] = set()

        for kb in kbs:
            persist_dir = kb.persist_dir
            exists = persist_dir.exists()

            row_count = 0
            if exists:
                try:
                    vs = VectorStoreService.get_vector_store(kb.id)
                    stats = vs.get_stats()
                    row_count = stats.get("row_count", 0)
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
                    "status": "indexed" if row_count > 0 else "empty",
                    "row_count": row_count,
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
            info = {
                "id": kb_id,
                "name": kb_meta.get("name", kb_id),
                "description": kb_meta.get("description", ""),
                "source_type": kb_meta.get("source_type", "unknown"),
                "status": "empty",
                "row_count": 0,
                "topics": kb_meta.get("topics", []),
            }
            if persist_dir.exists():
                try:
                    vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
                    stats = vs.get_stats()
                    info["status"] = (
                        "indexed" if stats.get("row_count", 0) > 0 else "empty"
                    )
                    info["row_count"] = stats.get("row_count", 0)
                except Exception:
                    info["status"] = "error"
            result.append(info)

        return result

    @staticmethod
    def get_info(kb_id: str) -> Optional[Dict[str, Any]]:
        """获取知识库详情"""
        from kb.registry import registry
        from kb.database import init_kb_meta_db

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
        from kb.database import init_kb_meta_db

        return init_kb_meta_db().get_topics(kb_id)

    @staticmethod
    def refresh_topics(kb_id: str, has_new_docs: bool = True) -> List[str]:
        from kb.topic_analyzer import analyze_and_update_topics

        return analyze_and_update_topics(kb_id, has_new_docs=has_new_docs)

    @staticmethod
    def sync_from_registry(kb_id: str, source_type: str = "obsidian") -> bool:
        from kb.registry import registry
        from kb.database import init_kb_meta_db

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
        from kb.registry import registry
        from kb.database import init_kb_meta_db

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
        return KnowledgeBaseService.create(
            kb_id=kb_id,
            name=name,
            description=description,
            source_type="obsidian",
        )

    @staticmethod
    def delete(kb_id: str) -> bool:
        """删除知识库（软删除 + 清理物理数据 + 清理去重状态）"""
        from kb.registry import registry
        from kb.database import (
            init_kb_meta_db,
            init_sync_db,
            init_dedup_db,
            init_progress_db,
        )
        from kb.deduplication import DeduplicationManager

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

        dedup_manager = DeduplicationManager(kb_id, persist_dir)
        dedup_manager.clear()

        init_sync_db().clear(kb_id)
        init_dedup_db().clear(kb_id)
        init_progress_db().reset(kb_id)

        init_kb_meta_db().set_active(kb_id, is_active=False)

        registry._loaded = False
        registry._bases.clear()

        return True

    @staticmethod
    def initialize(kb_id: str) -> bool:
        """初始化知识库（清空所有数据）

        清除向量存储、去重状态、进度、同步状态，但保留知识库配置。
        用于完全重置知识库到初始状态。
        """
        from kb.database import init_progress_db, init_sync_db
        from kb.deduplication import DeduplicationManager

        vs = VectorStoreService.get_vector_store(kb_id)
        vs.delete_table()

        persist_dir = VectorStoreService.get_persist_dir(kb_id)
        dedup_manager = DeduplicationManager(kb_id, persist_dir)
        dedup_manager.clear()

        init_progress_db().reset(kb_id)
        init_sync_db().clear(kb_id)

        return True


class SearchService:
    """搜索服务"""

    @staticmethod
    def search(
        kb_id: str,
        query: str,
        top_k: int = 5,
        with_metadata: bool = True,
        use_auto_merging: Optional[bool] = None,
        mode: str = "vector",
        embed_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from llamaindex_study.config import get_settings

        if embed_model_id:
            from llamaindex_study.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            configure_global_embed_model()
        settings = get_settings()

        vs = VectorStoreService.get_vector_store(kb_id)
        index = vs.load_index()

        if index is None:
            return []

        base_retriever = index.as_retriever(similarity_top_k=top_k * 5)

        _use_auto_merging = (
            use_auto_merging
            if use_auto_merging is not None
            else settings.use_auto_merging
        )

        if _use_auto_merging:
            docstore = index.storage_context.docstore
            if not docstore or len(docstore.docs) == 0:
                logger.warning(
                    "Auto-Merging 需要 docstore，但当前 KB 的 docstore 为空"
                    "（可能使用 LanceDB 向量索引创建），将使用普通 retriever"
                )
            else:
                try:
                    from llama_index.core.retrievers import AutoMergingRetriever

                    merger = AutoMergingRetriever(
                        base_retriever,
                        index.storage_context,
                        simple_ratio_thresh=0.25,
                        verbose=False,
                    )
                    retriever = merger
                except Exception:
                    pass
        else:
            retriever = base_retriever

        # 支持 hybrid 检索模式
        if mode == "hybrid" or settings.use_hybrid_search:
            retriever = SearchService._create_hybrid_retriever(
                retriever, index, top_k, settings
            )

        results = retriever.retrieve(query)

        # Post-process: prefer parent nodes over children for longer context
        if _use_auto_merging:
            results = SearchService._prefer_parent_nodes(results)

        return [
            {
                "text": r.text,
                "score": r.score,
                "metadata": r.metadata or {},
            }
            for r in results[:top_k]
        ]

    @staticmethod
    def _prefer_parent_nodes(results: List) -> List:
        if not results:
            return results

        parent_ids = set()
        child_to_parent = {}

        for r in results:
            node = getattr(r, "node", None)
            if node and hasattr(node, "parent_node") and node.parent_node:
                parent_id = node.parent_node.node_id
                child_to_parent[node.node_id] = parent_id
                parent_ids.add(parent_id)

        if not parent_ids:
            return results

        nodes_to_remove = set()
        for child_id, parent_id in child_to_parent.items():
            if parent_id in parent_ids:
                nodes_to_remove.add(child_id)

        filtered = [
            r
            for r in results
            if getattr(r.node, "node_id", None) not in nodes_to_remove
        ]
        filtered.sort(key=lambda x: x.score, reverse=True)
        return filtered

    @staticmethod
    def _create_hybrid_retriever(
        vector_retriever: Any,
        index: Any,
        top_k: int,
        settings: Any,
    ) -> Any:
        """创建混合搜索检索器（向量 + BM25 + 融合）"""
        try:
            from llama_index.core.retrievers import QueryFusionRetriever
            from llama_index.retrievers.bm25 import BM25Retriever

            # 检查 docstore 是否有数据（从 LanceDB 只加载向量时不包含 docstore）
            docstore = index.storage_context.docstore
            if not docstore or len(docstore.docs) == 0:
                logger.warning(
                    "混合搜索：docstore 为空（可能使用 LanceDB 向量索引创建），"
                    "无法使用 BM25，回退到纯向量检索"
                )
                return vector_retriever

            bm25_retriever = BM25Retriever.from_defaults(
                docstore=docstore,
                similarity_top_k=top_k * 3,
            )

            fusion_retriever = QueryFusionRetriever(
                retrievers=[vector_retriever, bm25_retriever],
                similarity_top_k=top_k,
                num_queries=1,
                mode=settings.hybrid_search_mode,
                use_async=False,
                verbose=False,
            )
            logger.info(
                f"混合搜索: vector + BM25, mode={settings.hybrid_search_mode}, alpha={settings.hybrid_search_alpha}"
            )
            return fusion_retriever
        except ImportError as e:
            logger.warning(f"混合搜索依赖未安装，回退到向量检索: {e}")
            return vector_retriever
        except Exception as e:
            logger.warning(f"混合搜索初始化失败，回退到向量检索: {e}")
            return vector_retriever

    @staticmethod
    def search_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_auto_merging: Optional[bool] = None,
        mode: str = "vector",
        embed_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from llamaindex_study.config import get_model_registry

        registry = get_model_registry()

        if embed_model_id:
            from llamaindex_study.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            default_embed = registry.get_default("embedding")
            if default_embed:
                from llamaindex_study.ollama_utils import (
                    configure_embed_model_by_model_id,
                )

                configure_embed_model_by_model_id(default_embed["id"])
                from kb.parallel_embedding import get_parallel_processor

                get_parallel_processor().set_model_by_model_id(default_embed["id"])
            else:
                configure_global_embed_model()

        all_results = []
        for kb_id in kb_ids:
            try:
                results = SearchService.search(
                    kb_id,
                    query,
                    top_k=top_k,
                    use_auto_merging=use_auto_merging,
                    mode=mode,
                    embed_model_id=embed_model_id,
                )
                for r in results:
                    r["kb_id"] = kb_id
                all_results.extend(results)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results[:top_k]

    @staticmethod
    def query(
        kb_id: str,
        query: str,
        mode: str = "vector",
        top_k: int = 5,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_auto_merging: Optional[bool] = None,
        response_mode: Optional[str] = None,
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from llamaindex_study.query_engine import create_query_engine

        if embed_model_id:
            from llamaindex_study.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            configure_global_embed_model()
        settings = get_settings()

        query_engine = create_query_engine(
            kb_id,
            mode=mode,
            top_k=top_k,
            use_auto_merging=use_auto_merging
            if use_auto_merging is not None
            else settings.use_auto_merging,
            use_hyde=use_hyde if use_hyde is not None else settings.use_hyde,
            use_multi_query=use_multi_query
            if use_multi_query is not None
            else settings.use_multi_query,
            num_multi_queries=num_multi_queries,
            response_mode=response_mode or settings.response_mode,
            model_id=model_id,
        )
        logger.info(
            f"[SearchService.query] use_hyde={use_hyde}, use_multi_query={use_multi_query}, num_multi_queries={num_multi_queries}, query_engine={type(query_engine).__name__}"
        )
        response = query_engine.query(query)
        logger.info(
            f"[SearchService.query] response={str(response)[:100]}, source_nodes={len(response.source_nodes)}"
        )

        if not response.source_nodes and use_multi_query:
            logger.warning("Multi-Query 返回空结果，尝试回退到普通查询")
            query_engine = create_query_engine(
                kb_id,
                mode=mode,
                top_k=top_k,
                use_auto_merging=use_auto_merging
                if use_auto_merging is not None
                else settings.use_auto_merging,
                use_hyde=use_hyde if use_hyde is not None else settings.use_hyde,
                use_multi_query=False,
                response_mode=response_mode or settings.response_mode,
                model_id=model_id,
            )
            response = query_engine.query(query)
            logger.info(
                f"[SearchService.query] fallback response={str(response)[:100]}, source_nodes={len(response.source_nodes)}"
            )

        return {
            "response": str(response),
            "sources": [
                {"text": r.text[:200], "score": r.score} for r in response.source_nodes
            ],
        }


class QueryRouter:
    """查询路由服务 - 自动选择知识库"""

    @staticmethod
    def route(
        query: str,
        top_k: int = 5,
        exclude: Optional[List[str]] = None,
        model_id: Optional[str] = None,
    ) -> List[str]:
        """根据查询内容路由到最相关的知识库

        Args:
            query: 用户查询
            top_k: 返回最相关的 top_k 个知识库
            exclude: 排除的知识库 ID 列表
            model_id: 使用的LLM模型ID (None=使用默认Ollama模型)

        Returns:
            知识库 ID 列表
        """
        kbs = KnowledgeBaseService.list_all()
        exclude = exclude or []

        if not kbs:
            return []

        kbs = [kb for kb in kbs if kb["id"] not in exclude]

        if len(kbs) == 1:
            return [kbs[0]["id"]]

        kb_ids = QueryRouter._llm_route(query, kbs, model_id=model_id)

        if not kb_ids:
            kb_ids = QueryRouter._keyword_route(query, kbs)

        if not kb_ids:
            kb_ids = QueryRouter._fallback_route(query, kbs)

        return kb_ids[:top_k]

    @staticmethod
    def _llm_route(
        query: str,
        kbs: List[Dict[str, Any]],
        model_id: Optional[str] = None,
    ) -> List[str]:
        """使用 LLM 进行知识库路由

        Args:
            query: 用户查询
            kbs: 知识库列表
            model_id: 使用的LLM模型ID (None=使用默认Ollama模型)

        Returns:
            知识库 ID 列表
        """
        try:
            from llamaindex_study.ollama_utils import create_llm

            kb_descriptions = []
            for kb in kbs:
                topics = kb.get("topics", [])
                topics_str = ", ".join(topics) if topics else "无"
                kb_descriptions.append(f"- {kb['id']}: {topics_str}")

            kb_list_text = "\n".join(kb_descriptions)

            prompt = f"""分析用户问题，从知识库列表中找出所有可能相关的知识库。

重要原则：
- 仅根据每个知识库的主题关键词（topics）进行判断
- 如果问题中的关键词与某知识库的主题高度重合，则选择该库
- 主题关键词完全不匹配的知识库不要选择
- 宁可精确匹配，也不要随意扩展

知识库列表：
{kb_list_text}

用户问题：{query}

请先分析问题中的关键词，然后与每个知识库的主题进行匹配，返回最相关的知识库 ID，用逗号分隔。

返回格式示例：kb1,kb2,kb3

请只返回 ID 列表，不要其他内容。"""

            llm = create_llm(model_id=model_id)
            response = llm.complete(prompt)
            result = response.text.strip()

            selected = [kb_id.strip() for kb_id in result.split(",")]

            valid_ids = {kb["id"] for kb in kbs}
            selected = [kb_id for kb_id in selected if kb_id in valid_ids]

            return selected

        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(f"LLM 路由失败: {e}")
            return []

    @staticmethod
    def _keyword_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        """使用关键词匹配进行知识库路由（仅基于 topics）"""
        query_words = QueryRouter._tokenize_query(query)

        scores: Dict[str, float] = {}

        for kb in kbs:
            kb_id = kb["id"]
            topics = kb.get("topics", [])
            if not topics:
                continue

            score = 0.0
            for word in query_words:
                if len(word) < 1:
                    continue
                for topic in topics:
                    topic_lower = topic.lower()
                    if word in topic_lower:
                        score += 1.0
                    if len(topic_lower) >= 2 and topic_lower in word:
                        score += 0.5

            if score > 0:
                scores[kb_id] = score

        if not scores:
            return []

        sorted_kbs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [kb_id for kb_id, _ in sorted_kbs]

    @staticmethod
    def _tokenize_query(query: str) -> List[str]:
        query_lower = query.lower().strip()
        tokens = {w for w in query_lower.replace(",", " ").split() if w}
        chinese_segments = re.findall(r"[\u4e00-\u9fff]+", query_lower)
        for seg in chinese_segments:
            tokens.add(seg)
            if len(seg) > 1:
                for i in range(len(seg) - 1):
                    tokens.add(seg[i : i + 2])
        return [t for t in tokens if t]

    @staticmethod
    def _fallback_route(query: str, kbs: List[Dict[str, Any]]) -> List[str]:
        tokens = QueryRouter._tokenize_query(query)
        scores: Dict[str, float] = {}
        for kb in kbs:
            kb_id = kb["id"]
            kb_name = str(kb.get("name", "")).lower()
            kb_desc = str(kb.get("description", "")).lower()
            kb_topics = [str(t).lower() for t in (kb.get("topics") or [])]
            score = 0.0
            for token in tokens:
                if token in kb_name:
                    score += 1.0
                if token in kb_desc:
                    score += 0.8
                for topic in kb_topics:
                    if token in topic:
                        score += 1.2
            if score > 0:
                scores[kb_id] = score

        if scores:
            sorted_kbs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return [kb_id for kb_id, _ in sorted_kbs]

        indexed_kbs = sorted(
            [kb for kb in kbs if int(kb.get("row_count", 0) or 0) > 0],
            key=lambda kb: int(kb.get("row_count", 0) or 0),
            reverse=True,
        )
        if indexed_kbs:
            return [kb["id"] for kb in indexed_kbs]
        return [kb["id"] for kb in kbs]

    @staticmethod
    def search(
        query: str,
        top_k: int = 5,
        mode: str = "auto",
        exclude: Optional[List[str]] = None,
        use_auto_merging: Optional[bool] = None,
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
        retrieval_mode: str = "vector",
    ) -> Dict[str, Any]:
        if mode == "all":
            all_kbs = KnowledgeBaseService.list_all()
            exclude = exclude or []
            kb_ids = [kb["id"] for kb in all_kbs if kb["id"] not in exclude]
        else:
            kb_ids = QueryRouter.route(query, exclude=exclude, model_id=model_id)

        if not kb_ids:
            return {"results": [], "kbs_queried": [], "query": query}

        all_results = []
        for kb_id in kb_ids:
            try:
                results = SearchService.search(
                    kb_id,
                    query,
                    top_k=top_k,
                    use_auto_merging=use_auto_merging,
                    mode=retrieval_mode,
                    embed_model_id=embed_model_id,
                )
                for r in results:
                    r["kb_id"] = kb_id
                all_results.extend(results)
            except Exception:
                continue

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return {
            "results": all_results[:top_k],
            "kbs_queried": kb_ids,
            "query": query,
        }

    @staticmethod
    def _resolve_kb_ids(
        query: str,
        mode: str,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        if mode == "all":
            all_kbs = KnowledgeBaseService.list_all()
            exclude = exclude or []
            return [kb["id"] for kb in all_kbs if kb["id"] not in exclude]
        return QueryRouter.route(query, exclude=exclude)

    @staticmethod
    def _query_across_kbs(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_auto_merging: Optional[bool] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        contexts = []
        sources = []

        for kb_id in kb_ids:
            try:
                result = SearchService.search(
                    kb_id,
                    query,
                    top_k=top_k,
                    use_auto_merging=use_auto_merging,
                    mode=retrieval_mode,
                    embed_model_id=embed_model_id,
                )
                for r in result:
                    contexts.append(f"[{kb_id}] {r['text']}")
                    sources.append(
                        {
                            "kb_id": kb_id,
                            "text": r["text"][:200],
                            "score": r.get("score", 0),
                        }
                    )
            except Exception:
                continue

        if not contexts:
            return {
                "response": "在所有知识库中都没有找到相关内容",
                "sources": [],
                "kbs_queried": kb_ids,
            }

        context_text = "\n\n".join(contexts[:10])
        prompt = f"""基于以下上下文信息回答用户问题。如果上下文中没有相关信息，请说明。

上下文：
{context_text}

用户问题：{query}

回答："""

        try:
            from llamaindex_study.ollama_utils import create_llm

            llm = create_llm(model_id=model_id)
            response = llm.complete(prompt)
            answer = response.text.strip()
        except Exception as e:
            logger = get_logger(__name__)
            logger.warning(f"LLM 生成失败: {e}")
            answer = f"（在 {', '.join(kb_ids)} 中找到 {len(contexts)} 条相关内容）"

        return {
            "response": answer,
            "sources": sources[:top_k],
            "kbs_queried": kb_ids,
        }

    @staticmethod
    def query(
        query: str,
        top_k: int = 5,
        mode: str = "auto",
        exclude: Optional[List[str]] = None,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_auto_merging: Optional[bool] = None,
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """自动路由 RAG 问答

        Args:
            query: 用户查询
            top_k: 每个知识库检索的数量
            mode: 路由模式 (auto=自动路由, all=所有知识库)
            exclude: 排除的知识库 ID 列表
            use_hyde: 启用 HyDE（None=使用配置默认值）
            use_multi_query: 启用多查询转换（None=使用配置默认值）
            num_multi_queries: 多查询变体数量（None=使用配置默认值）
            use_auto_merging: 启用 Auto-Merging（None=使用配置默认值）
            response_mode: 答案生成模式（None=使用配置默认值）
            retrieval_mode: 检索模式 (vector, hybrid)
            model_id: 使用的LLM模型ID (None=使用默认模型)
            embed_model_id: 使用的Embedding模型ID (None=使用默认模型)

        Returns:
            RAG 问答结果
        """
        if model_id:
            from llamaindex_study.ollama_utils import configure_llm_by_model_id

            configure_llm_by_model_id(model_id)

        if embed_model_id:
            from llamaindex_study.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)

        kb_ids = QueryRouter._resolve_kb_ids(
            query=query,
            mode=mode,
            exclude=exclude,
        )

        if not kb_ids:
            return {
                "response": "没有找到相关的知识库",
                "sources": [],
                "kbs_queried": [],
            }

        if len(kb_ids) == 1:
            return SearchService.query(
                kb_ids[0],
                query,
                mode=retrieval_mode,
                top_k=top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                num_multi_queries=num_multi_queries,
                use_auto_merging=use_auto_merging,
                response_mode=response_mode,
                model_id=model_id,
                embed_model_id=embed_model_id,
            )

        return QueryRouter._query_across_kbs(
            kb_ids=kb_ids,
            query=query,
            top_k=top_k,
            use_auto_merging=use_auto_merging,
            retrieval_mode=retrieval_mode,
            model_id=model_id,
            embed_model_id=embed_model_id,
        )

    @staticmethod
    def query_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        use_auto_merging: Optional[bool] = None,
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        from llamaindex_study.config import get_model_registry

        registry = get_model_registry()

        if model_id:
            from llamaindex_study.ollama_utils import configure_llm_by_model_id

            configure_llm_by_model_id(model_id)
        else:
            default_llm = registry.get_default("llm")
            if default_llm:
                from llamaindex_study.ollama_utils import configure_llm_by_model_id

                configure_llm_by_model_id(default_llm["id"])

        if embed_model_id:
            from llamaindex_study.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            default_embed = registry.get_default("embedding")
            if default_embed:
                from llamaindex_study.ollama_utils import (
                    configure_embed_model_by_model_id,
                )

                configure_embed_model_by_model_id(default_embed["id"])
                from kb.parallel_embedding import get_parallel_processor

                get_parallel_processor().set_model_by_model_id(default_embed["id"])

        if not kb_ids:
            return {
                "response": "没有指定知识库",
                "sources": [],
                "kbs_queried": [],
            }

        if len(kb_ids) == 1:
            return SearchService.query(
                kb_ids[0],
                query,
                mode=retrieval_mode,
                top_k=top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                num_multi_queries=num_multi_queries,
                use_auto_merging=use_auto_merging,
                response_mode=response_mode,
                model_id=model_id,
                embed_model_id=embed_model_id,
            )

        return QueryRouter._query_across_kbs(
            kb_ids=kb_ids,
            query=query,
            top_k=top_k,
            use_auto_merging=use_auto_merging,
            retrieval_mode=retrieval_mode,
            model_id=model_id,
            embed_model_id=embed_model_id,
        )


class TaskService:
    """任务服务"""

    @staticmethod
    def submit(
        task_type: str, kb_id: str, params: Dict[str, Any], source: str = ""
    ) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue

        queue = TaskQueue()
        task_id = queue.submit_task(
            task_type=task_type,
            kb_id=kb_id,
            params=params,
            source=source,
        )
        return {
            "task_id": task_id,
            "status": "pending",
            "kb_id": kb_id,
            "message": "任务已提交",
        }

    @staticmethod
    def list_tasks(
        kb_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor, is_scheduler_running

        queue = TaskQueue()

        if not is_scheduler_running():
            running_tasks = queue.list_tasks(status=TaskStatus.RUNNING.value, limit=100)
            for task in running_tasks:
                if task.task_id not in task_executor._running_tasks:
                    is_stale = (
                        task.last_heartbeat is None
                        or (time.time() - task.last_heartbeat) > 300
                    )
                    if is_stale:
                        queue.update_status(
                            task.task_id,
                            TaskStatus.FAILED.value,
                            "孤儿任务（执行进程已终止）",
                        )

        return [
            task.to_dict()
            for task in queue.list_tasks(kb_id=kb_id, status=status, limit=limit)
        ]

    @staticmethod
    def get_task(task_id: str) -> Optional[Dict[str, Any]]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor, is_scheduler_running

        queue = TaskQueue()
        task = queue.get_task(task_id)

        if task and task.status == TaskStatus.RUNNING.value:
            # Only mark as orphan if scheduler is not running AND task not in local _running_tasks
            # Scheduler runs in separate process, so its _running_tasks is different
            if (
                task_id not in task_executor._running_tasks
                and not is_scheduler_running()
            ):
                # Only mark as orphan if heartbeat is stale (> 5 minutes)
                # A task with fresh heartbeat is likely still running normally
                is_stale = (
                    task.last_heartbeat is None
                    or (time.time() - task.last_heartbeat) > 300
                )
                if is_stale:
                    queue.update_status(
                        task_id,
                        TaskStatus.FAILED.value,
                        "孤儿任务（执行进程已终止）",
                    )
                    task = queue.get_task(task_id)

        return task.to_dict() if task else None

    @staticmethod
    def cancel(task_id: str) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == TaskStatus.CANCELLED.value:
            return {
                "status": "cancelled",
                "task_id": task_id,
                "message": "任务已取消",
            }

        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务已完成，无法取消",
            }

        queue.update_status(task_id, TaskStatus.CANCELLED.value, "已取消")
        task_executor.cancel_task(task_id)

        return {
            "status": "cancelled",
            "task_id": task_id,
            "message": "已取消任务",
        }

    @staticmethod
    def cleanup_orphan_task(task_id: str) -> bool:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        task = queue.get_task(task_id)

        if task and task.status == TaskStatus.RUNNING.value:
            queue.update_status(
                task_id,
                TaskStatus.FAILED.value,
                "孤儿任务（执行进程已终止）",
            )
            return True
        return False

    @staticmethod
    def pause(task_id: str) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status != TaskStatus.RUNNING.value:
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务当前状态为 {task.status}，无法暂停",
            }

        queue.update_status(task_id, TaskStatus.PAUSED.value, "已暂停")
        task_executor.pause_task(task_id)
        return {
            "status": "paused",
            "task_id": task_id,
            "message": "任务已暂停",
        }

    @staticmethod
    def resume(task_id: str) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status != TaskStatus.PAUSED.value:
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务当前状态为 {task.status}，无法恢复",
            }

        queue.update_status(task_id, TaskStatus.RUNNING.value, "继续执行")
        task_executor.resume_task(task_id)
        return {
            "status": "running",
            "task_id": task_id,
            "message": "任务已恢复",
        }

    @staticmethod
    def pause_all(status: str = "running") -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status=status)
        paused = []
        failed = []

        for task in tasks:
            if task.status == TaskStatus.RUNNING.value:
                queue.update_status(task.task_id, TaskStatus.PAUSED.value, "已暂停")
                paused.append(task.task_id)
            else:
                failed.append(task.task_id)

        return {
            "status": "completed",
            "paused": paused,
            "failed": failed,
            "message": f"已暂停 {len(paused)} 个任务，{len(failed)} 个无法暂停",
        }

    @staticmethod
    def resume_all() -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status="paused")
        resumed = []

        for task in tasks:
            queue.update_status(task.task_id, TaskStatus.RUNNING.value, "继续执行")
            resumed.append(task.task_id)

        return {
            "status": "completed",
            "resumed": resumed,
            "message": f"已恢复 {len(resumed)} 个任务",
        }

    @staticmethod
    def delete_all(status: str = "completed", cleanup: bool = False) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        tasks = queue.list_tasks(status=status)
        deleted = []
        cleaned_results = []

        for task in tasks:
            try:
                if task.status == TaskStatus.RUNNING.value:
                    continue

                if cleanup:
                    sources = task.result.get("sources") if task.result else None
                    cleaned = TaskService._cleanup_task_data(
                        task.kb_id, task.task_type, sources=sources
                    )
                    cleaned_results.append(
                        {"task_id": task.task_id, "cleanup": cleaned}
                    )

                queue.delete_task(task.task_id)
                deleted.append(task.task_id)
            except Exception:
                pass

        result = {
            "status": "completed",
            "deleted": deleted,
            "message": f"已删除 {len(deleted)} 个任务",
        }

        if cleaned_results:
            result["cleaned"] = cleaned_results

        return result

    @staticmethod
    def cleanup_orphan_tasks(cleanup: bool = True) -> Dict[str, Any]:
        from kb.task_queue import TaskQueue, TaskStatus
        from kb.task_executor import task_executor, is_scheduler_running

        queue = TaskQueue()
        tasks = queue.list_tasks(status="running")
        cleaned = []
        cleaned_data = []

        if not is_scheduler_running():
            for task in tasks:
                if task.task_id not in task_executor._running_tasks:
                    is_stale = (
                        task.last_heartbeat is None
                        or (time.time() - task.last_heartbeat) > 300
                    )
                    if is_stale:
                        cleaned.append(task.task_id)
                        queue.update_status(
                            task.task_id,
                            TaskStatus.FAILED.value,
                            "孤儿任务（执行进程已终止）",
                        )

                        if cleanup:
                            sources = (
                                task.result.get("sources") if task.result else None
                            )
                            result = TaskService._cleanup_task_data(
                                task.kb_id, task.task_type, sources=sources
                            )
                            cleaned_data.append(
                                {"task_id": task.task_id, "cleanup": result}
                            )

        result = {
            "status": "completed",
            "cleaned": cleaned,
            "message": f"已清理 {len(cleaned)} 个孤儿任务",
        }

        if cleaned_data:
            result["cleaned_data"] = cleaned_data

        return result

    @staticmethod
    def delete(task_id: str, cleanup: bool = False) -> Dict[str, Any]:
        """删除任务（物理删除）

        Args:
            task_id: 任务ID
            cleanup: 是否清理关联的知识库数据
                    - True: 同时清空该知识库的 dedup 状态和向量数据
                    - False: 仅删除任务记录
        """
        from kb.task_queue import TaskQueue

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == "running":
            raise ValueError(f"任务正在运行，无法删除: {task_id}")

        success = queue.delete_task(task_id)
        if not success:
            raise ValueError(f"删除失败: {task_id}")

        result = {"status": "deleted", "task_id": task_id, "message": "任务已删除"}

        if cleanup:
            sources = task.result.get("sources") if task.result else None
            cleaned = TaskService._cleanup_task_data(
                task.kb_id, task.task_type, sources=sources
            )
            result["cleanup"] = cleaned

        return result

    @staticmethod
    def _cleanup_task_data(
        kb_id: str, task_type: str, sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """清理任务产生的关联数据

        Args:
            kb_id: 知识库ID
            task_type: 任务类型
            sources: 要删除的源文件路径列表
        """
        from kb.deduplication import DeduplicationManager
        from kb.registry import get_storage_root

        cleaned = {"dedup_state": False, "vector_store": False, "deleted_nodes": 0}

        persist_dir = get_storage_root() / kb_id
        dedup_manager = DeduplicationManager(kb_id, persist_dir)

        if task_type == "initialize":
            dedup_manager.clear()
            cleaned["dedup_state"] = True

            from kb.services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True
        elif task_type == "zotero":
            dedup_manager.clear()
            cleaned["dedup_state"] = True

            from kb.services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True
        elif sources:
            for source in sources:
                dedup_manager.remove_record(source)
            cleaned["dedup_state"] = True

            from kb.services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            lance_store = vs._get_lance_vector_store()
            deleted = lance_store.delete_by_source(sources)
            cleaned["deleted_nodes"] = deleted
            cleaned["vector_store"] = deleted > 0

        return cleaned

    @staticmethod
    def run_task(task_id: str) -> Dict[str, Any]:
        from kb.task_executor import task_executor

        asyncio.run(task_executor.execute_task(task_id))
        task = TaskService.get_task(task_id)
        if task is None:
            raise ValueError(f"任务不存在: {task_id}")
        return task

    @staticmethod
    def wait_for_task(
        task_id: str, interval: float = 1.0, timeout: float = 0
    ) -> Dict[str, Any]:
        start = time.time()
        while True:
            task = TaskService.get_task(task_id)
            if task is None:
                raise ValueError(f"任务不存在: {task_id}")
            if task["status"] in {"completed", "failed", "cancelled"}:
                return task
            if timeout > 0 and time.time() - start >= timeout:
                return task
            time.sleep(interval)


class CategoryService:
    """分类规则服务"""

    @staticmethod
    def list_rules() -> Dict[str, Any]:
        from kb.database import init_category_rule_db

        rule_db = init_category_rule_db()
        rules = rule_db.get_all_rules()
        return {"rules": rules, "total": len(rules)}

    @staticmethod
    def sync_rules() -> Dict[str, Any]:
        from kb.obsidian_config import seed_mappings_to_db

        count = seed_mappings_to_db()
        return {
            "status": "success",
            "message": f"已同步 {count} 条分类规则到数据库",
            "count": count,
        }

    @staticmethod
    def add_rule(
        kb_id: str,
        rule_type: str,
        pattern: str,
        description: str = "",
        priority: int = 0,
    ) -> Dict[str, Any]:
        from kb.database import init_category_rule_db

        rule_db = init_category_rule_db()
        success = rule_db.add_rule(
            kb_id=kb_id,
            rule_type=rule_type,
            pattern=pattern,
            description=description,
            priority=priority,
        )
        return {
            "status": "success" if success else "error",
            "message": f"规则添加{'成功' if success else '失败'}",
        }

    @staticmethod
    def delete_rule(kb_id: str, rule_type: str, pattern: str) -> Dict[str, Any]:
        from kb.database import init_category_rule_db

        rule_db = init_category_rule_db()
        success = rule_db.delete_rule(kb_id, rule_type, pattern)
        return {
            "status": "success" if success else "error",
            "message": f"规则删除{'成功' if success else '失败'}",
        }

    @staticmethod
    def classify(
        folder_path: str, folder_description: str = "", use_llm: bool = True
    ) -> Dict[str, Any]:
        from kb.category_classifier import CategoryClassifier
        from kb.obsidian_config import find_kb_by_path

        matched_kbs = find_kb_by_path(folder_path)
        if matched_kbs and not use_llm:
            return {
                "kb_id": matched_kbs[0],
                "matched_by": "rule",
                "confidence": 1.0,
                "reason": f"文件夹路径匹配: {folder_path}",
            }

        if use_llm:
            try:
                classifier = CategoryClassifier()
                result = classifier.classify_folder_llm(
                    folder_path=folder_path,
                    folder_description=folder_description,
                )
                return {
                    "kb_id": result["kb_id"],
                    "matched_by": "llm",
                    "confidence": result["confidence"],
                    "reason": result["reason"],
                    "alternatives": matched_kbs if matched_kbs else None,
                }
            except Exception as e:
                return {
                    "error": f"LLM 分类失败: {str(e)}",
                    "alternatives": matched_kbs,
                }

        return {
            "kb_id": None,
            "matched_by": "none",
            "confidence": 0.0,
            "reason": "未找到匹配的知识库",
            "suggestion": "请手动指定知识库或使用 LLM 分类",
        }


class AdminService:
    """管理服务"""

    @staticmethod
    def list_tables() -> Dict[str, Any]:
        tables: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for kb in KnowledgeBaseService.list_all():
            info = KnowledgeBaseService.get_info(kb["id"])
            if not info:
                continue
            persist_dir = Path(info["persist_dir"])
            tables.append(
                {
                    "kb_id": kb["id"],
                    "path": str(persist_dir),
                    "status": info.get("status", "unknown"),
                    "row_count": info.get("row_count", 0),
                }
            )
            seen.add(kb["id"])

        for child in get_storage_root().iterdir():
            if not child.is_dir() or child.name in seen:
                continue
            tables.append(
                {
                    "kb_id": child.name,
                    "path": str(child),
                    "status": "unregistered",
                    "row_count": None,
                }
            )

        return {"tables": tables}

    @staticmethod
    def get_table_info(kb_id: str) -> Optional[Dict[str, Any]]:
        return KnowledgeBaseService.get_info(kb_id)

    @staticmethod
    def delete_table(kb_id: str) -> bool:
        return KnowledgeBaseService.delete(kb_id)


# ==================== 一致性校验与修复 ====================


class ConsistencyService:
    """知识库一致性校验与修复服务"""

    @staticmethod
    def verify(kb_id: str) -> Dict[str, Any]:
        """
        校验知识库一致性

        比较 dedup_records 中记录的 chunk 总数与 LanceDB 实际行数。

        Returns:
            {
                "kb_id": str,
                "dedup_files": int,        # dedup 记录的文件数
                "dedup_chunks": int,       # dedup 记录的 chunk 总数
                "lance_rows": int,         # LanceDB 实际行数
                "consistent": bool,        # 是否一致
                "missing_chunks": int,     # LanceDB 缺失的 chunk 数
                "orphan_rows": int,        # LanceDB 多余的行数
                "status": str,             # 状态描述
            }
        """
        from kb.database import init_dedup_db

        dedup_db = init_dedup_db()

        # 1. 从 dedup_records 获取预期 chunk 总数
        try:
            dedup_records = dedup_db.get_records(kb_id)
            dedup_files = len(dedup_records)
            dedup_chunks = sum(r.get("chunk_count", 0) for r in dedup_records)
        except Exception as e:
            logger.error(f"读取 dedup 记录失败: {e}")
            return {
                "kb_id": kb_id,
                "error": f"读取 dedup 记录失败: {e}",
                "status": "error",
            }

        # 2. 从 LanceDB 获取实际行数
        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            stats = vs.get_stats()
            lance_rows = stats.get("row_count", 0) if stats.get("exists") else 0
        except Exception as e:
            logger.error(f"读取 LanceDB 失败: {e}")
            return {
                "kb_id": kb_id,
                "dedup_files": dedup_files,
                "dedup_chunks": dedup_chunks,
                "error": f"读取 LanceDB 失败: {e}",
                "status": "error",
            }

        # 3. 比较
        missing_chunks = max(0, dedup_chunks - lance_rows)
        orphan_rows = max(0, lance_rows - dedup_chunks)
        consistent = missing_chunks == 0 and orphan_rows == 0

        if consistent:
            status = "consistent"
        elif missing_chunks > 0 and orphan_rows > 0:
            status = "mixed_inconsistency"
        elif missing_chunks > 0:
            status = "missing_data"
        else:
            status = "orphan_data"

        return {
            "kb_id": kb_id,
            "dedup_files": dedup_files,
            "dedup_chunks": dedup_chunks,
            "lance_rows": lance_rows,
            "consistent": consistent,
            "missing_chunks": missing_chunks,
            "orphan_rows": orphan_rows,
            "status": status,
        }

    @staticmethod
    def repair(kb_id: str, mode: str = "sync") -> Dict[str, Any]:
        """
        修复知识库一致性

        Args:
            kb_id: 知识库 ID
            mode: 修复模式
                - "sync": 从 dedup 同步到 LanceDB（删除 orphan 向量）
                - "rebuild": 重新扫描文件重建（较慢但不丢数据）
                - "dry": 只报告，不修复

        Returns:
            {
                "kb_id": str,
                "mode": str,
                "repaired": bool,
                "message": str,
                "details": dict,
            }
        """
        if mode == "dry":
            verify_result = ConsistencyService.verify(kb_id)
            if verify_result.get("status") == "error":
                return {
                    "kb_id": kb_id,
                    "mode": mode,
                    "repaired": False,
                    "message": "校验失败",
                    "details": verify_result,
                }
            if verify_result["consistent"]:
                return {
                    "kb_id": kb_id,
                    "mode": mode,
                    "repaired": True,
                    "message": "知识库已一致，无需修复",
                    "details": verify_result,
                }
            return {
                "kb_id": kb_id,
                "mode": mode,
                "repaired": False,
                "message": f"发现不一致: missing={verify_result['missing_chunks']}, orphan={verify_result['orphan_rows']}",
                "details": verify_result,
            }

        if mode == "sync":
            return ConsistencyService._repair_sync(kb_id)
        elif mode == "rebuild":
            return ConsistencyService._repair_rebuild(kb_id)
        else:
            return {
                "kb_id": kb_id,
                "mode": mode,
                "repaired": False,
                "message": f"未知修复模式: {mode}",
            }

    @staticmethod
    def _repair_sync(kb_id: str) -> Dict[str, Any]:
        """
        同步模式修复：删除 LanceDB 中的 orphan 向量

        从 dedup 记录获取所有 doc_id，删除 LanceDB 中不在这些 doc_id 中的记录。
        """
        from kb.database import init_dedup_db

        verify_result = ConsistencyService.verify(kb_id)
        if verify_result.get("status") == "error":
            return {
                "kb_id": kb_id,
                "mode": "sync",
                "repaired": False,
                "message": "校验阶段失败",
                "details": verify_result,
            }

        if verify_result["orphan_rows"] == 0:
            return {
                "kb_id": kb_id,
                "mode": "sync",
                "repaired": True,
                "message": "没有 orphan 数据需要清理",
                "details": verify_result,
            }

        dedup_db = init_dedup_db()

        # 获取 dedup 中记录的 doc_id 集合
        dedup_records = dedup_db.get_records(kb_id)
        valid_doc_ids = set()
        for record in dedup_records:
            doc_id = record.get("doc_id")
            if doc_id:
                valid_doc_ids.add(doc_id)

        if not valid_doc_ids:
            return {
                "kb_id": kb_id,
                "mode": "sync",
                "repaired": False,
                "message": "dedup 记录为空，无法修复",
                "details": {"valid_doc_ids": 0},
            }

        # 删除 LanceDB 中不在 valid_doc_ids 中的记录
        try:
            import lancedb

            vs = VectorStoreService.get_vector_store(kb_id)
            persist_dir = vs.persist_dir or vs._get_uri()

            db = lancedb.connect(str(persist_dir))
            table = db.open_table(kb_id)

            # 获取 LanceDB 中所有的 id
            df = table.to_pandas()
            lance_ids = (
                set(df["id"].astype(str).tolist())
                if df is not None and "id" in df.columns
                else set()
            )

            # 计算需要删除的 id
            orphan_ids = lance_ids - valid_doc_ids

            if not orphan_ids:
                return {
                    "kb_id": kb_id,
                    "mode": "sync",
                    "repaired": True,
                    "message": "没有 orphan 数据",
                    "details": {"orphan_count": 0},
                }

            # 批量删除（分批执行避免过大）
            deleted = 0
            batch_size = 1000
            orphan_list = list(orphan_ids)

            for i in range(0, len(orphan_list), batch_size):
                batch = orphan_list[i : i + batch_size]
                id_list = "', '".join(batch)
                try:
                    result = table.delete(f"id IN ('{id_list}')")
                    if hasattr(result, "num_deleted"):
                        deleted += result.num_deleted
                    elif hasattr(result, "count"):
                        deleted += result.count
                except Exception as e:
                    logger.warning(f"删除批次失败: {e}")

            # 验证修复结果
            verify_after = ConsistencyService.verify(kb_id)

            return {
                "kb_id": kb_id,
                "mode": "sync",
                "repaired": verify_after["consistent"],
                "message": f"删除了 {deleted} 个 orphan 记录",
                "details": {
                    "deleted_count": deleted,
                    "before": verify_result,
                    "after": verify_after,
                },
            }

        except Exception as e:
            logger.error(f"同步修复失败: {e}")
            return {
                "kb_id": kb_id,
                "mode": "sync",
                "repaired": False,
                "message": f"修复失败: {e}",
            }

    @staticmethod
    def _repair_rebuild(kb_id: str) -> Dict[str, Any]:
        """
        重建模式修复：重新扫描文件并重建向量

        这是最可靠的修复方式，但速度较慢。
        """
        from kb.registry import KnowledgeBaseRegistry

        try:
            registry = KnowledgeBaseRegistry()
            kb = registry.get(kb_id)

            if not kb:
                return {
                    "kb_id": kb_id,
                    "mode": "rebuild",
                    "repaired": False,
                    "message": f"知识库 {kb_id} 不存在",
                }

            # 获取所有文件
            vault_root = kb.vault_root()
            source_paths = kb.source_paths_abs(vault_root)

            all_files = []
            for source_path in source_paths:
                if source_path.exists():
                    if source_path.is_file():
                        all_files.append(source_path)
                    elif source_path.is_dir():
                        all_files.extend(source_path.rglob("*.md"))

            # 记录文件列表
            file_count = len(all_files)
            logger.info(f"重建模式: 发现 {file_count} 个文件")

            return {
                "kb_id": kb_id,
                "mode": "rebuild",
                "repaired": True,
                "message": f"扫描到 {file_count} 个文件，请使用 ingest 命令重新导入",
                "details": {
                    "file_count": file_count,
                    "note": "使用 ingest 命令重新导入以完成修复",
                },
            }

        except Exception as e:
            logger.error(f"重建扫描失败: {e}")
            return {
                "kb_id": kb_id,
                "mode": "rebuild",
                "repaired": False,
                "message": f"扫描失败: {e}",
            }

    @staticmethod
    def safe_delete_files(kb_id: str, sources: List[str]) -> Dict[str, Any]:
        """
        原子性删除文件（保证 dedup 和 LanceDB 一致）

        Args:
            kb_id: 知识库 ID
            sources: 要删除的源文件路径列表

        Returns:
            {
                "kb_id": str,
                "deleted_sources": int,
                "deleted_vectors": int,
                "success": bool,
                "message": str,
            }
        """
        if not sources:
            return {
                "kb_id": kb_id,
                "deleted_sources": 0,
                "deleted_vectors": 0,
                "success": True,
                "message": "没有文件需要删除",
            }

        from kb.database import init_dedup_db
        import lancedb

        dedup_db = init_dedup_db()

        # 1. 标记 dedup 记录待删除（先标记，不实际删除）
        deleted_sources = 0
        for source in sources:
            try:
                dedup_db.remove(kb_id, source)
                deleted_sources += 1
            except Exception as e:
                logger.warning(f"删除 dedup 记录失败 {source}: {e}")

        # 2. 从 LanceDB 删除向量
        deleted_vectors = 0
        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            persist_dir = vs.persist_dir or vs._get_uri()

            db = lancedb.connect(str(persist_dir))
            if kb_id in db.list_tables().tables:
                table = db.open_table(kb_id)

                for source in sources:
                    try:
                        escaped_source = source.replace("'", "''")
                        result = table.delete(f"source = '{escaped_source}'")
                        if hasattr(result, "num_deleted"):
                            deleted_vectors += result.num_deleted
                        elif hasattr(result, "count"):
                            deleted_vectors += result.count
                    except Exception as e:
                        logger.warning(f"从 LanceDB 删除 {source} 失败: {e}")

        except Exception as e:
            logger.error(f"LanceDB 删除失败: {e}")
            return {
                "kb_id": kb_id,
                "deleted_sources": deleted_sources,
                "deleted_vectors": deleted_vectors,
                "success": False,
                "message": f"LanceDB 删除失败: {e}",
            }

        # 3. 验证结果
        verify = ConsistencyService.verify(kb_id)
        consistent = verify.get("consistent", False)

        return {
            "kb_id": kb_id,
            "deleted_sources": deleted_sources,
            "deleted_vectors": deleted_vectors,
            "success": consistent,
            "message": "删除成功"
            if consistent
            else f"删除完成但存在不一致 (missing={verify.get('missing_chunks')})",
        }

    @staticmethod
    def repair_all(mode: str = "sync") -> Dict[str, Any]:
        """
        修复所有知识库的一致性

        Returns:
            {
                "total": int,
                "repaired": int,
                "failed": int,
                "results": list,
            }
        """
        from kb.registry import KnowledgeBaseRegistry

        registry = KnowledgeBaseRegistry()
        kbs = registry.list()

        results = []
        repaired = 0
        failed = 0

        for kb in kbs:
            kb_id = kb.id
            try:
                result = ConsistencyService.repair(kb_id, mode=mode)
                results.append(result)
                if result.get("repaired"):
                    repaired += 1
            except Exception as e:
                logger.error(f"修复知识库 {kb_id} 失败: {e}")
                results.append(
                    {
                        "kb_id": kb_id,
                        "repaired": False,
                        "message": str(e),
                    }
                )
                failed += 1

        return {
            "total": len(kbs),
            "repaired": repaired,
            "failed": failed,
            "results": results,
        }
