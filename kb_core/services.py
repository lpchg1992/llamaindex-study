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

from rag.config import get_settings
from rag.logger import get_logger
from rag.vector_store import LanceDBVectorStore
from rag.ollama_utils import (
    create_parallel_ollama_embedding,
    configure_global_embed_model,
)
from kb_core.registry import get_storage_root
from .document_chunk_service import get_document_chunk_service

logger = get_logger(__name__)


# =============================================================================
# SECTION 1: VectorStoreService
# Responsibility: Vector store lifecycle management
# Dependencies: None within services.py
# =============================================================================

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
            from .database import init_kb_meta_db

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
        from .database import init_kb_meta_db

        kb_meta = init_kb_meta_db().get(kb_id)
        if kb_meta:
            source_type = kb_meta.get("source_type", "generic")
        else:
            source_type = "generic"
        return VectorStoreService._get_persist_dir_by_source_type(kb_id, source_type)


# =============================================================================
# SECTION 2: ObsidianService
# Responsibility: Obsidian vault import orchestration
# Dependencies: VectorStoreService
# =============================================================================

class ObsidianService:
    """Obsidian 导入服务"""

    @staticmethod
    def get_vaults() -> List[Dict[str, Any]]:
        """获取可用的 Obsidian Vault 列表"""
        from kb_core.registry import get_vault_root

        vault_path = str(get_vault_root())

        vaults = [
            {
                "name": "默认",
                "path": vault_path,
            },
        ]

        try:
            from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

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
        from kb_core.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

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
    def get_vault_structure(
        vault_name: str, folder_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取 Vault 文件夹的层级结构

        Args:
            vault_name: Vault 名称
            folder_path: 子文件夹路径（None 表示根目录）

        Returns:
            层级结构
        """
        from kb_core.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

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
                    return {"error": f"未找到 Vault: {vault_name}"}
            except ImportError:
                return {"error": "无法加载 Vault 配置"}

        if not vault_path.exists():
            return {"error": f"Vault 路径不存在: {vault_path}"}

        target_dir = vault_path if not folder_path else vault_path / folder_path
        if not target_dir.exists():
            return {"error": f"文件夹不存在: {target_dir}"}

        items = []
        for item in sorted(target_dir.iterdir()):
            if item.name.startswith("."):
                continue

            if item.is_dir():
                md_count = len(list(item.glob("*.md")))
                items.append(
                    {
                        "type": "folder",
                        "name": item.name,
                        "path": str(item.relative_to(vault_path)),
                        "md_count": md_count,
                    }
                )
            elif item.suffix == ".md":
                size = item.stat().st_size
                items.append(
                    {
                        "type": "file",
                        "name": item.name,
                        "path": str(item.relative_to(vault_path)),
                        "size": size,
                    }
                )

        return {
            "vault_name": vault_name,
            "vault_path": str(vault_path),
            "folder_path": folder_path or "",
            "items": items,
        }

    @staticmethod
    def get_vault_tree(vault_name: str) -> Dict[str, Any]:
        """
        获取 Vault 的完整树形结构（仅顶层文件夹，用于懒加载）

        Args:
            vault_name: Vault 名称

        Returns:
            树形结构
        """
        from kb_core.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

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
                    return {"error": f"未找到 Vault: {vault_name}"}
            except ImportError:
                return {"error": "无法加载 Vault 配置"}

        if not vault_path.exists():
            return {"error": f"Vault 路径不存在: {vault_path}"}

        def build_tree(dir_path: Path, depth: int = 0) -> List[Dict[str, Any]]:
            if depth > 3:
                return []

            result = []
            for item in sorted(dir_path.iterdir()):
                if item.name.startswith("."):
                    continue

                if item.is_dir():
                    md_count = len(list(item.glob("*.md")))
                    children = build_tree(item, depth + 1) if depth < 2 else []
                    result.append(
                        {
                            "type": "folder",
                            "name": item.name,
                            "path": str(item.relative_to(vault_path)),
                            "md_count": md_count,
                            "has_children": len(children) > 0,
                            "children": children,
                        }
                    )
                elif item.suffix == ".md":
                    result.append(
                        {
                            "type": "file",
                            "name": item.name,
                            "path": str(item.relative_to(vault_path)),
                            "size": item.stat().st_size,
                        }
                    )

            return result

        return {
            "vault_name": vault_name,
            "vault_path": str(vault_path),
            "items": build_tree(vault_path),
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
        from kb_obsidian.processor import ObsidianImporter
        from kb_processing.document_processor import DocumentProcessorConfig

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


# =============================================================================
# SECTION 3: ZoteroService
# Responsibility: Zotero collection import
# Dependencies: VectorStoreService, KnowledgeBaseService.refresh_topics
# =============================================================================

class ZoteroService:
    """Zotero 导入服务"""

    @staticmethod
    def list_collections() -> List[Dict[str, Any]]:
        """列出所有收藏夹"""
        from kb_zotero.processor import ZoteroImporter

        importer = ZoteroImporter()
        collections = importer.get_collections()
        importer.close()

        return collections

    @staticmethod
    def search_collections(q: str) -> List[Dict[str, Any]]:
        """搜索收藏夹"""
        from kb_zotero.processor import ZoteroImporter

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
        from kb_zotero.processor import ZoteroImporter
        from kb_processing.document_processor import DocumentProcessorConfig, ProcessingProgress

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

        if rebuild:
            vs.delete_table()
            progress = ProcessingProgress()

        importer = ZoteroImporter(kb_id=kb_id)
        try:
            stats = importer.import_collection(
                collection_id=collection_id,
                collection_name=collection_name,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=progress,
                rebuild=rebuild,
                progress_file=progress_file,
                kb_id=kb_id,
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

    @staticmethod
    def import_item(
        kb_id: str,
        item_id: str,
        options: Optional[Dict[str, Any]] = None,
        refresh_topics: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
        prefix: str = "[kb]",
    ) -> Dict[str, Any]:
        """
        导入单个 Zotero 文献

        Args:
            kb_id: 知识库 ID
            item_id: 文献 ID
            options: 个性化选项，如 force_ocr
            progress_callback: 进度回调
            prefix: 附件标题前缀标记

        Returns:
            导入统计
        """
        from kb_zotero.processor import ZoteroImporter
        from kb_processing.document_processor import ProcessingProgress

        if progress_callback:
            progress_callback(f"开始导入 Zotero 文献: {item_id}")

        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = vs.persist_dir or Path.home() / ".llamaindex" / "storage" / kb_id

        importer = ZoteroImporter(kb_id=kb_id)
        try:
            item = importer.get_item(int(item_id), prefix=prefix)
            if not item:
                raise ValueError(f"文献不存在: {item_id}")

            progress = ProcessingProgress()

            force_ocr = options.get("force_ocr", False) if options else False
            is_scanned_override = options.get("is_scanned") if options else None
            has_md_cache = options.get("has_md_cache") if options else None

            logger.info(
                f"[ZoteroService.import_item] item_id={item_id}, prefix={prefix}, file_path={item.file_path}, force_ocr={force_ocr}, is_scanned_override={is_scanned_override}, has_md_cache={has_md_cache}"
            )
            nodes, all_nodes, processed_sources, error_reason = importer.import_item(
                item=item,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=progress,
                kb_id=kb_id,
                force_ocr=force_ocr,
                is_scanned=is_scanned_override,
                has_md_cache=has_md_cache,
            )

            if progress_callback:
                progress_callback(f"完成！导入 {nodes} 个节点")

            if refresh_topics:
                KnowledgeBaseService.refresh_topics(kb_id=kb_id, has_new_docs=nodes > 0)

            result = {
                "items": 1,
                "nodes": nodes,
                "processed_sources": processed_sources,
            }
            if error_reason:
                result["error"] = error_reason
            return result

        finally:
            importer.close()

    @staticmethod
    def get_collection_structure(collection_id: str) -> Dict[str, Any]:
        """
        获取收藏夹的层级结构（包含子收藏夹和文献）

        Args:
            collection_id: 收藏夹 ID

        Returns:
            层级结构
        """
        from kb_zotero.processor import ZoteroImporter

        importer = ZoteroImporter()
        try:
            # 获取当前收藏夹信息
            collections = importer.get_collections()
            current_collection = None
            for c in collections:
                if str(c.get("collectionID")) == str(collection_id):
                    current_collection = c
                    break

            if not current_collection:
                return {"error": f"未找到收藏夹: {collection_id}"}

            # 获取所有子收藏夹
            sub_collections = [
                c
                for c in collections
                if c.get("parentCollectionID") == int(collection_id)
            ]

            # 获取当前收藏夹中的文献
            item_ids = importer.get_items_in_collection(
                int(collection_id), recursive=False
            )

            items = []
            for item_id in item_ids[:100]:  # 限制返回数量，避免过多
                item = importer.get_item(item_id)
                if item:
                    items.append(
                        {
                            "item_id": item.item_id,
                            "title": item.title,
                            "creators": item.creators,
                            "has_file": bool(item.file_path),
                            "has_annotations": len(item.annotations) > 0,
                            "has_notes": len(item.notes) > 0,
                        }
                    )

            return {
                "collection_id": collection_id,
                "collection_name": current_collection.get("collectionName", ""),
                "parent_id": current_collection.get("parentCollectionID"),
                "sub_collections": [
                    {
                        "collection_id": c.get("collectionID"),
                        "name": c.get("collectionName", ""),
                    }
                    for c in sub_collections
                ],
                "items": items,
                "item_count": len(items),
            }
        finally:
            importer.close()

    @staticmethod
    def get_all_collections_with_items() -> List[Dict[str, Any]]:
        """
        获取所有收藏夹及其直接文献（用于树形展示）

        Returns:
            所有收藏夹列表
        """
        from kb_zotero.processor import ZoteroImporter

        importer = ZoteroImporter()
        try:
            collections = importer.get_collections()

            # 构建层级结构
            result = []
            for collection in collections:
                collection_id = collection.get("collectionID")
                item_ids = importer.get_items_in_collection(
                    collection_id, recursive=False
                )

                items = []
                for item_id in item_ids[:50]:  # 限制每个收藏夹返回的数量
                    item = importer.get_item(item_id)
                    if item:
                        items.append(
                            {
                                "item_id": item.item_id,
                                "title": item.title,
                                "has_file": bool(item.file_path),
                            }
                        )

                result.append(
                    {
                        "collection_id": collection_id,
                        "collection_name": collection.get("collectionName", ""),
                        "parent_id": collection.get("parentCollectionID"),
                        "items": items,
                        "item_count": len(items),
                    }
                )

            return result
        finally:
            importer.close()


# =============================================================================
# SECTION 4: GenericService
# Responsibility: Generic file import
# Dependencies: VectorStoreService
# =============================================================================

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
        from kb_processing.generic_processor import GenericImporter

        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"文件不存在: {path}")

        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = VectorStoreService.get_persist_dir(kb_id)
        importer = GenericImporter(kb_id=kb_id, persist_dir=persist_dir)

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


# =============================================================================
# SECTION 5: KnowledgeBaseService
# Responsibility: KB CRUD, settings, topics management
# Dependencies: VectorStoreService, TaskService._cleanup_task_data
# =============================================================================

class KnowledgeBaseService:
    """知识库管理服务"""

    @staticmethod
    def list_all() -> List[Dict[str, Any]]:
        """列出所有知识库"""
        from kb_core.registry import registry
        from .database import init_kb_meta_db, init_document_db

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
        from .database import init_kb_meta_db

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
        from .database import init_kb_meta_db

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
        from .database import init_kb_meta_db

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
        from .database import init_kb_meta_db

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
        from .database import init_kb_meta_db

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
        from .database import (
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
                from .database import ChunkModel

                session.execute(delete(ChunkModel).where(ChunkModel.kb_id == kb_id))

            # 删除该 KB 的所有 documents
            with doc_db.db.session_scope() as session:
                from .database import DocumentModel

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
        from .database import init_progress_db, init_document_db, init_chunk_db
        from sqlalchemy import delete

        vs = VectorStoreService.get_vector_store(kb_id)
        vs.delete_table()

        # 清理 SQLite documents 和 chunks
        try:
            doc_db = init_document_db()
            chunk_db = init_chunk_db()

            with chunk_db.db.session_scope() as session:
                from .database import ChunkModel

                session.execute(delete(ChunkModel).where(ChunkModel.kb_id == kb_id))

            with doc_db.db.session_scope() as session:
                from .database import DocumentModel

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
# SECTION 6: SearchService
# Responsibility: RAG query execution
# Dependencies: KnowledgeBaseService, QueryRouter (circular)
# =============================================================================

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
        from rag.config import get_settings

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

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
            try:
                from rag.vector_store import LanceDBDocumentStore

                lance_docstore = LanceDBDocumentStore(kb_id=kb_id)
                lance_doc_count = len(lance_docstore)
                if lance_doc_count > 0:
                    logger.info(f"LanceDB docstore 有 {lance_doc_count} 个节点")
                    index.storage_context.docstore = lance_docstore

                    from llama_index.core.retrievers import AutoMergingRetriever

                    merger = AutoMergingRetriever(
                        base_retriever,
                        index.storage_context,
                        simple_ratio_thresh=0.25,
                        verbose=False,
                    )
                    retriever = merger
                    logger.info("Auto-Merging 已启用（使用 LanceDBDocumentStore）")
                else:
                    logger.warning("LanceDB docstore 为空，无法启用 Auto-Merging")
            except Exception as e:
                logger.warning(f"Auto-Merging 初始化失败: {e}")
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
        """优先返回父节点而非子节点
        
        在 Auto-Merging 检索模式下，优先返回较大的父节点，
        减少冗余并提供更完整的上下文。
        
        Args:
            results: 检索结果列表
            
        Returns:
            去重排序后的结果
        """
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
        """使用 LanceDB 原生混合搜索（向量 + FTS/BM25）"""
        import lancedb
        from llama_index.core.vector_stores.types import VectorStoreQueryMode
        from llama_index.core.indices.vector_store.retrievers import (
            VectorIndexRetriever,
        )

        vector_store = index.vector_store
        if hasattr(vector_store, "_get_lance_vector_store"):
            lance_store = vector_store._get_lance_vector_store()
        else:
            lance_store = vector_store

        if hasattr(lance_store, "ensure_fts_index"):
            lance_store.ensure_fts_index()

        if settings.hybrid_search_mode == "RRF":
            reranker = lancedb.rerankers.RRFReranker()
        else:
            reranker = lancedb.rerankers.LinearCombinationReranker(
                weight=settings.hybrid_search_alpha
            )

        if hasattr(lance_store, "_reranker"):
            lance_store._reranker = reranker

        hybrid_retriever = VectorIndexRetriever(
            index,
            similarity_top_k=top_k,
            vector_store_query_mode=VectorStoreQueryMode.HYBRID,
            alpha=settings.hybrid_search_alpha,
        )

        logger.info(
            f"混合搜索: LanceDB 原生 hybrid, mode={settings.hybrid_search_mode}, alpha={settings.hybrid_search_alpha}"
        )
        return hybrid_retriever

    @staticmethod
    def search_multi(
        kb_ids: List[str],
        query: str,
        top_k: int = 5,
        use_auto_merging: Optional[bool] = None,
        mode: str = "vector",
        embed_model_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from rag.config import get_model_registry

        registry = get_model_registry()

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            default_embed = registry.get_default("embedding")
            if default_embed:
                from rag.ollama_utils import (
                    configure_embed_model_by_model_id,
                )

                configure_embed_model_by_model_id(default_embed["id"])
                from kb_processing.parallel_embedding import get_parallel_processor

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
        from rag.query_engine import create_query_engine

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

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
                {"text": r.text, "score": r.score} for r in response.source_nodes
            ],
        }


# =============================================================================
# SECTION 7: QueryRouter
# Responsibility: Auto-routing across KBs
# Dependencies: KnowledgeBaseService, SearchService (circular with SearchService)
# =============================================================================

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
            from rag.ollama_utils import create_llm

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
        use_hyde: Optional[bool] = None,
        use_multi_query: Optional[bool] = None,
        num_multi_queries: Optional[int] = None,
        response_mode: Optional[str] = None,
        retrieval_mode: str = "vector",
        model_id: Optional[str] = None,
        embed_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        all_sources = []
        kb_responses = []

        for kb_id in kb_ids:
            try:
                result = SearchService.query(
                    kb_id,
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
                kb_responses.append(f"[{kb_id}]\n{result['response']}")

                # Add kb_id to each source
                for src in result.get("sources", []):
                    src["kb_id"] = kb_id
                    all_sources.append(src)
            except Exception as e:
                logger = get_logger(__name__)
                logger.warning(f"知识库 {kb_id} 查询失败: {e}")
                continue

        if not kb_responses:
            return {
                "response": "在所有知识库中都没有找到相关内容",
                "sources": [],
                "kbs_queried": kb_ids,
            }

        # Sort sources by score descending
        all_sources.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Combine responses from all KBs
        combined_response = "\n\n---\n\n".join(kb_responses)

        return {
            "response": combined_response,
            "sources": all_sources[: top_k * 3],
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
            from rag.ollama_utils import configure_llm_by_model_id

            configure_llm_by_model_id(model_id)

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

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
            use_hyde=use_hyde,
            use_multi_query=use_multi_query,
            num_multi_queries=num_multi_queries,
            response_mode=response_mode,
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
        from rag.config import get_model_registry

        registry = get_model_registry()

        if model_id:
            from rag.ollama_utils import configure_llm_by_model_id

            configure_llm_by_model_id(model_id)
        else:
            default_llm = registry.get_default("llm")
            if default_llm:
                from rag.ollama_utils import configure_llm_by_model_id

                configure_llm_by_model_id(default_llm["id"])

        if embed_model_id:
            from rag.ollama_utils import configure_embed_model_by_model_id

            configure_embed_model_by_model_id(embed_model_id)
            from kb_processing.parallel_embedding import get_parallel_processor

            get_parallel_processor().set_model_by_model_id(embed_model_id)
        else:
            default_embed = registry.get_default("embedding")
            if default_embed:
                from rag.ollama_utils import (
                    configure_embed_model_by_model_id,
                )

                configure_embed_model_by_model_id(default_embed["id"])
                from kb_processing.parallel_embedding import get_parallel_processor

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
            use_hyde=use_hyde,
            use_multi_query=use_multi_query,
            num_multi_queries=num_multi_queries,
            response_mode=response_mode,
            retrieval_mode=retrieval_mode,
            model_id=model_id,
            embed_model_id=embed_model_id,
        )


# =============================================================================
# SECTION 8: TaskService
# Responsibility: Task lifecycle management
# Dependencies: KnowledgeBaseService, VectorStoreService, ConsistencyService
# =============================================================================

class TaskService:
    """任务服务"""

    @staticmethod
    def submit(
        task_type: str, kb_id: str, params: Dict[str, Any], source: str = ""
    ) -> Dict[str, Any]:
        from .task_queue import TaskQueue

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
        """列出任务
        
        Args:
            kb_id: 知识库 ID（可选，None 表示所有）
            status: 任务状态过滤（可选）
            limit: 返回数量限制
            
        Returns:
            任务列表
        """
        from .task_queue import TaskQueue, TaskStatus
        from .task_executor import task_executor, is_scheduler_running

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
        """获取任务详情
        
        自动检测孤儿任务（执行进程已终止但状态仍为 running）。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务信息字典，不存在则返回 None
        """
        from .task_queue import TaskQueue, TaskStatus
        from .task_executor import task_executor, is_scheduler_running

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
    def cancel(task_id: str, cleanup: bool = False) -> Dict[str, Any]:
        """取消任务

        Args:
            task_id: 任务ID
            cleanup: 是否清理已处理的数据（默认 False）
        """
        from .task_queue import TaskQueue, TaskStatus
        from .task_executor import task_executor

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == TaskStatus.CANCELLED.value:
            result = {
                "status": "cancelled",
                "task_id": task_id,
                "message": "任务已取消",
            }
            if cleanup:
                result["cleanup"] = TaskService._cleanup_task_data(
                    task.kb_id,
                    task.task_type,
                    sources=task.result.get("partial_sources") if task.result else None,
                )
            return result

        if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
            return {
                "status": task.status,
                "task_id": task_id,
                "message": f"任务已完成，无法取消",
            }

        queue.update_status(task_id, TaskStatus.CANCELLED.value, "已取消")
        task_executor.cancel_and_wait(task_id, timeout=5.0)

        result = {
            "status": "cancelled",
            "task_id": task_id,
            "message": "已取消任务",
        }

        if cleanup:
            task = queue.get_task(task_id)
            if task and task.result:
                partial_sources = task.result.get("partial_sources", [])
                if partial_sources:
                    result["cleanup"] = TaskService._cleanup_task_data(
                        task.kb_id, task.task_type, sources=partial_sources
                    )

        return result

    @staticmethod
    def cleanup_orphan_task(task_id: str) -> bool:
        """清理单个孤儿任务
        
        将状态为 RUNNING 但心跳已过期的任务标记为失败。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            是否成功清理
        """
        from .task_queue import TaskQueue, TaskStatus

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
        from .task_queue import TaskQueue, TaskStatus
        from .task_executor import task_executor

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
        from .task_queue import TaskQueue, TaskStatus
        from .task_executor import task_executor

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
        """暂停所有指定状态的任务
        
        Args:
            status: 要暂停的任务状态，默认为 "running"
            
        Returns:
            操作结果统计
        """
        from .task_queue import TaskQueue, TaskStatus

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
        """恢复所有已暂停的任务
        
        Returns:
            操作结果统计
        """
        from .task_queue import TaskQueue, TaskStatus

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
        """批量删除任务
        
        Args:
            status: 删除指定状态的任务，"all" 表示所有
            cleanup: 是否同时清理关联的知识库数据
            
        Returns:
            操作结果统计
        """
        from .task_queue import TaskQueue, TaskStatus

        queue = TaskQueue()
        if status == "all":
            tasks = queue.list_tasks(limit=1000)
        else:
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
        """清理所有孤儿任务
        
        检测并标记执行进程已终止但状态仍为 running 的任务。
        
        Args:
            cleanup: 是否同时清理关联数据
            
        Returns:
            清理结果统计
        """
        from .task_queue import TaskQueue, TaskStatus
        from .task_executor import task_executor, is_scheduler_running

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
    def delete(task_id: str, cleanup: Optional[bool] = None) -> Dict[str, Any]:
        """删除任务（物理删除）

        Args:
            task_id: 任务ID
            cleanup: 是否清理关联的知识库数据（可选）
                    - None: 自动模式（任务状态为 failed/cancelled 时自动清理）
                    - True: 强制清理
                    - False: 不清理
        """
        from .task_queue import TaskQueue

        queue = TaskQueue()
        task = queue.get_task(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")

        if task.status == "running":
            raise ValueError(f"任务正在运行，无法删除: {task_id}")

        if task.status == "cancelled":
            from .task_executor import task_executor

            task_executor.cancel_and_wait(task_id, timeout=5.0)

        success = queue.delete_task(task_id)
        if not success:
            raise ValueError(f"删除失败: {task_id}")

        result = {"status": "deleted", "task_id": task_id, "message": "任务已删除"}

        should_cleanup = cleanup if cleanup is not None else False
        if task.status in ("failed", "cancelled"):
            should_cleanup = True

        if should_cleanup:
            sources = task.result.get("sources") if task.result else None
            if not sources:
                sources = task.result.get("partial_sources") if task.result else None
            cleaned = TaskService._cleanup_task_data(
                task.kb_id, task.task_type, sources=sources
            )
            result["cleanup"] = cleaned

        return result

    @staticmethod
    def _cleanup_task_data(
        kb_id: str,
        task_type: str,
        sources: Optional[List[str]] = None,
        cleanup_mode: str = "sources",
    ) -> Dict[str, Any]:
        """清理任务产生的关联数据

        Args:
            kb_id: 知识库ID
            task_type: 任务类型
            sources: 要删除的源文件路径列表
            cleanup_mode:
                - "full": 清空整个知识库数据（仅用于 initialize 类型）
                - "sources": 只清理指定的 sources（推荐，用于取消/删除任务）
        """
        cleaned = {
            "dedup_state": True,
            "vector_store": False,
            "documents": False,
            "chunks": False,
            "deleted_nodes": 0,
        }

        if task_type == "initialize" or cleanup_mode == "full":
            from .services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True

            doc_service = get_document_chunk_service(kb_id)
            all_docs = doc_service.get_all_documents()
            for doc in all_docs:
                doc_service.delete_document_cascade(
                    doc["id"],
                    delete_lance=False,
                )
            cleaned["documents"] = True
            cleaned["chunks"] = True

        elif task_type == "zotero" and cleanup_mode == "full":
            cleaned["dedup_state"] = True

            from .services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            vs.delete_table()
            cleaned["vector_store"] = True

            doc_service = get_document_chunk_service(kb_id)
            all_docs = doc_service.get_all_documents()
            for doc in all_docs:
                doc_service.delete_document_cascade(
                    doc["id"],
                    delete_lance=False,
                )
            cleaned["documents"] = True
            cleaned["chunks"] = True

        elif sources:
            cleaned["dedup_state"] = True

            from .services import VectorStoreService

            vs = VectorStoreService.get_vector_store(kb_id)
            lance_store = vs._get_lance_vector_store()
            deleted = lance_store.delete_by_source(sources)
            cleaned["deleted_nodes"] = deleted
            cleaned["vector_store"] = deleted > 0

            doc_service = get_document_chunk_service(kb_id)
            for source in sources:
                result = doc_service.delete_documents_by_source(source)
                if result.get("documents", 0) > 0:
                    cleaned["documents"] = cleaned.get("documents", 0) + result.get(
                        "documents", 0
                    )
                    cleaned["chunks"] = cleaned.get("chunks", 0) + result.get(
                        "chunks", 0
                    )

        return cleaned

    @staticmethod
    def run_task(task_id: str) -> Dict[str, Any]:
        """立即执行任务
        
        同步执行单个任务（阻塞直到完成）。
        
        Args:
            task_id: 任务 ID
            
        Returns:
            执行完成后的任务状态
            
        Raises:
            ValueError: 任务不存在
        """
        from .task_executor import task_executor

        asyncio.run(task_executor.execute_task(task_id))
        task = TaskService.get_task(task_id)
        if task is None:
            raise ValueError(f"任务不存在: {task_id}")
        return task

    @staticmethod
    def wait_for_task(
        task_id: str, interval: float = 1.0, timeout: float = 0
    ) -> Dict[str, Any]:
        """等待任务完成
        
        轮询任务状态直到完成或超时。
        
        Args:
            task_id: 任务 ID
            interval: 轮询间隔（秒）
            timeout: 超时时间（秒），0 表示无限等待
            
        Returns:
            最终任务状态
        """
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


# =============================================================================
# SECTION 9: CategoryService
# Responsibility: Category management
# Dependencies: None
# =============================================================================

class CategoryService:
    """分类规则服务"""

    @staticmethod
    def list_rules() -> Dict[str, Any]:
        """列出所有分类规则
        
        Returns:
            包含规则列表和总数的字典
        """
        from .database import init_category_rule_db

        rule_db = init_category_rule_db()
        rules = rule_db.get_all_rules()
        return {"rules": rules, "total": len(rules)}

    @staticmethod
    def sync_rules() -> Dict[str, Any]:
        """从 obsidian_config 同步分类规则到数据库
        
        Returns:
            同步结果统计
        """
        from kb_obsidian.config import seed_mappings_to_db

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
        """添加分类规则
        
        Args:
            kb_id: 知识库 ID
            rule_type: 规则类型 (folder_path / tag)
            pattern: 匹配模式
            description: 规则描述
            priority: 优先级
            
        Returns:
            操作结果
        """
        from .database import init_category_rule_db

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
        """删除分类规则
        
        Args:
            kb_id: 知识库 ID
            rule_type: 规则类型
            pattern: 匹配模式
            
        Returns:
            操作结果
        """
        from .database import init_category_rule_db

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
        from kb_analysis.category_classifier import CategoryClassifier
        from kb_obsidian.config import find_kb_by_path

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


# =============================================================================
# SECTION 10: AdminService
# Responsibility: Admin operations
# Dependencies: KnowledgeBaseService
# =============================================================================

class AdminService:
    """管理服务"""

    @staticmethod
    def list_tables() -> Dict[str, Any]:
        """列出所有知识库的表信息
        
        包括已注册的知识库和存储目录中存在但未注册的知识库。
        
        Returns:
            知识库表列表
        """
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
        """获取知识库表详情
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            知识库详细信息
        """
        return KnowledgeBaseService.get_info(kb_id)

    @staticmethod
    def delete_table(kb_id: str) -> bool:
        """删除知识库（从 AdminService）
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            是否成功
        """
        return KnowledgeBaseService.delete(kb_id)


# ==================== 一致性校验与修复 ====================


# =============================================================================
# SECTION 11: ConsistencyService
# Responsibility: KB consistency check/repair
# Dependencies: KnowledgeBaseService, VectorStoreService, TaskService._cleanup_task_data
# =============================================================================

class ConsistencyService:
    """知识库一致性校验与修复服务"""

    @staticmethod
    def check(kb_id: str) -> Dict[str, Any]:
        """
        统一的一致性检查

        检查两个维度：
        1. 文档统计准确性：documents.chunk_count vs chunks 表实际数量
        2. 向量完整性：LanceDB 行数与文档统计的匹配情况

        Returns:
            {
                "kb_id": str,
                "status": str,  # "ok" | "issues_found"
                "summary": {
                    "doc_count": int,
                    "chunk_count_stored": int,  # documents.chunk_count 总和
                    "chunk_count_actual": int,  # chunks 表实际数量
                    "lance_rows": int,          # LanceDB 行数
                },
                "doc_stats": {
                    "accurate": bool,
                    "mismatched_count": int,
                    "issues": [...],
                },
                "vector_integrity": {
                    "status": str,  # "ok" | "missing" | "orphan" | "mismatch"
                    "missing_count": int,   # LanceDB 缺少的 chunk 数
                    "orphan_count": int,    # LanceDB 多余的 chunk 数
                    "issues": [...],
                },
                "recommendations": [...],  # 建议采取的行动
            }
        """
        from .database import init_document_db, init_chunk_db

        doc_db = init_document_db()
        chunk_db = init_chunk_db()
        docs = doc_db.get_by_kb(kb_id)

        if not docs:
            return {
                "kb_id": kb_id,
                "status": "ok",
                "summary": {
                    "doc_count": 0,
                    "chunk_count_stored": 0,
                    "chunk_count_actual": 0,
                    "lance_rows": 0,
                },
                "doc_stats": {"accurate": True, "mismatched_count": 0, "issues": []},
                "vector_integrity": {
                    "status": "ok",
                    "missing_count": 0,
                    "orphan_count": 0,
                    "issues": [],
                },
                "recommendations": [],
            }

        chunk_count_stored = 0
        chunk_count_actual = 0
        doc_stats_issues = []

        for doc in docs:
            doc_id = doc.get("id")
            stored = doc.get("chunk_count", 0)
            actual = chunk_db.count_by_doc(doc_id)
            chunk_count_stored += stored
            chunk_count_actual += actual

            if stored != actual:
                diff = actual - stored
                doc_stats_issues.append(
                    {
                        "doc_id": doc_id,
                        "source_file": doc.get("source_file", ""),
                        "stored": stored,
                        "actual": actual,
                        "diff": diff,
                        "description": f"文档 {doc.get('source_file') or doc_id} 记录 {stored} chunks，实际 {actual} chunks (差异: {diff:+d})",
                    }
                )

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            stats = vs.get_stats()
            lance_rows = stats.get("row_count", 0) if stats.get("exists") else 0
        except Exception as e:
            logger.error(f"读取 LanceDB 失败: {e}")
            return {
                "kb_id": kb_id,
                "error": f"读取 LanceDB 失败: {e}",
                "status": "error",
            }

        missing_count = max(0, chunk_count_stored - lance_rows)
        orphan_count = max(0, lance_rows - chunk_count_actual)
        actual_mismatch = lance_rows - chunk_count_stored

        embedding_stats = chunk_db.get_embedding_stats(kb_id)
        emb_success = embedding_stats.get("success", 0)
        emb_pending = embedding_stats.get("pending", 0)
        emb_failed = embedding_stats.get("failed", 0)
        emb_total = embedding_stats.get("total", 0)

        vector_issues = []
        if missing_count > 0:
            vector_issues.append(
                {
                    "type": "missing",
                    "count": missing_count,
                    "description": f"LanceDB 缺少 {missing_count} 个 chunk（documents 记录存在但 LanceDB 没有）",
                }
            )
        if orphan_count > 0:
            if doc_stats_issues:
                vector_issues.append(
                    {
                        "type": "orphan_stats_error",
                        "count": orphan_count,
                        "description": f"LanceDB 比 documents.chunk_count 总和多 {orphan_count} 个，可能是统计错误导致",
                    }
                )
            else:
                vector_issues.append(
                    {
                        "type": "orphan_real",
                        "count": orphan_count,
                        "description": f"LanceDB 有 {orphan_count} 个 chunk 无法匹配到 documents 记录",
                    }
                )

        recommendations = []
        if doc_stats_issues:
            recommendations.append(
                {
                    "action": "fix_doc_stats",
                    "priority": "high",
                    "description": f"修正 {len(doc_stats_issues)} 个文档的 chunk_count 统计（安全操作，不删数据）",
                }
            )
        if missing_count > 0:
            recommendations.append(
                {
                    "action": "reimport",
                    "priority": "high",
                    "description": f"LanceDB 缺少 {missing_count} 个 chunk，需要重新导入相关文档",
                }
            )
        if orphan_count > 0 and not doc_stats_issues:
            recommendations.append(
                {
                    "action": "investigate",
                    "priority": "medium",
                    "description": f"存在 {orphan_count} 个无法匹配的 LanceDB 记录，需要人工确认",
                }
            )

        has_issues = len(doc_stats_issues) > 0 or missing_count > 0 or orphan_count > 0

        return {
            "kb_id": kb_id,
            "status": "issues_found" if has_issues else "ok",
            "summary": {
                "doc_count": len(docs),
                "chunk_count_stored": chunk_count_stored,
                "chunk_count_actual": chunk_count_actual,
                "lance_rows": lance_rows,
            },
            "doc_stats": {
                "accurate": len(doc_stats_issues) == 0,
                "mismatched_count": len(doc_stats_issues),
                "issues": doc_stats_issues,
            },
            "embedding_stats": {
                "total": emb_total,
                "success": emb_success,
                "pending": emb_pending,
                "failed": emb_failed,
                "in_lance": min(emb_success, lance_rows),
                "missing_in_lance": max(0, emb_success - lance_rows),
                "pending_not_in_lance": emb_pending,
                "failed_not_in_lance": emb_failed,
            },
            "vector_integrity": {
                "status": "ok"
                if not vector_issues
                else vector_issues[0].get("type", "unknown"),
                "missing_count": missing_count,
                "orphan_count": orphan_count,
                "issues": vector_issues,
            },
            "recommendations": recommendations,
        }

    @staticmethod
    def verify(kb_id: str) -> Dict[str, Any]:
        """
        校验知识库一致性（兼容旧接口）

        比较 documents 表中的 chunk 总数与 LanceDB 实际行数。
        """
        from .database import init_document_db

        doc_db = init_document_db()
        docs = doc_db.get_by_kb(kb_id)
        doc_files = len(docs)
        doc_chunks = sum(d.get("chunk_count", 0) for d in docs)

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            stats = vs.get_stats()
            lance_rows = stats.get("row_count", 0) if stats.get("exists") else 0
        except Exception as e:
            logger.error(f"读取 LanceDB 失败: {e}")
            return {
                "kb_id": kb_id,
                "error": f"读取 LanceDB 失败: {e}",
                "status": "error",
            }

        missing_chunks = max(0, doc_chunks - lance_rows)
        orphan_rows = max(0, lance_rows - doc_chunks)
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
            "doc_files": doc_files,
            "doc_chunks": doc_chunks,
            "lance_rows": lance_rows,
            "consistent": consistent,
            "missing_chunks": missing_chunks,
            "orphan_rows": orphan_rows,
            "status": status,
        }

    @staticmethod
    def verify_doc_stats(kb_id: str) -> Dict[str, Any]:
        """
        校验文档级别的 chunk_count 准确性

        比较每个文档的 documents.chunk_count 与 chunks 表中的实际数量。
        不修改任何数据，只报告问题。
        """
        from .database import init_document_db, init_chunk_db

        doc_db = init_document_db()
        chunk_db = init_chunk_db()

        docs = doc_db.get_by_kb(kb_id)
        mismatched_docs = []
        total_stored_count = 0
        total_actual_count = 0

        for doc in docs:
            doc_id = doc.get("id")
            stored_count = doc.get("chunk_count", 0)
            actual_count = chunk_db.count_by_doc(doc_id)

            total_stored_count += stored_count
            total_actual_count += actual_count

            if stored_count != actual_count:
                mismatched_docs.append(
                    {
                        "doc_id": doc_id,
                        "source_file": doc.get("source_file", ""),
                        "stored_count": stored_count,
                        "actual_count": actual_count,
                        "diff": actual_count - stored_count,
                    }
                )

        return {
            "kb_id": kb_id,
            "total_documents": len(docs),
            "mismatched_count": len(mismatched_docs),
            "total_stored_count": total_stored_count,
            "total_actual_count": total_actual_count,
            "mismatched_docs": mismatched_docs,
            "is_accurate": len(mismatched_docs) == 0,
        }

    @staticmethod
    def fix_doc_stats(kb_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        修复文档的 chunk_count 和 total_chars 统计信息

        此方法只更新 documents 表的统计字段，不涉及任何数据删除。
        通过查询 chunks 表的实际数量来更新统计值。

        Args:
            kb_id: 知识库 ID
            dry_run: 如果为 True，只报告会做什么，不实际执行修改

        Returns:
            {
                "kb_id": str,
                "mode": str,
                "fixed": int,
                "skipped": int,
                "details": [...],
            }
        """
        from .database import init_document_db
        from .document_chunk_service import get_document_chunk_service

        doc_db = init_document_db()
        docs = doc_db.get_by_kb(kb_id)

        if not docs:
            return {
                "kb_id": kb_id,
                "mode": "fix_stats",
                "fixed": 0,
                "skipped": 0,
                "message": "没有文档需要修复",
            }

        service = get_document_chunk_service(kb_id=kb_id)
        fixed = 0
        skipped = 0
        details = []

        for doc in docs:
            doc_id = doc.get("id")
            stored_count = doc.get("chunk_count", 0)

            if dry_run:
                from .database import init_chunk_db

                chunk_db = init_chunk_db()
                actual_count = chunk_db.count_by_doc(doc_id)
                if stored_count != actual_count:
                    details.append(
                        {
                            "doc_id": doc_id,
                            "source_file": doc.get("source_file", ""),
                            "stored_count": stored_count,
                            "actual_count": actual_count,
                            "action": "would_fix",
                        }
                    )
                else:
                    skipped += 1
            else:
                success = service.update_document_stats(doc_id)
                if success:
                    fixed += 1
                    details.append(
                        {
                            "doc_id": doc_id,
                            "source_file": doc.get("source_file", ""),
                            "stored_count": stored_count,
                            "action": "fixed",
                        }
                    )
                else:
                    skipped += 1
                    details.append(
                        {
                            "doc_id": doc_id,
                            "source_file": doc.get("source_file", ""),
                            "action": "failed",
                        }
                    )

        return {
            "kb_id": kb_id,
            "mode": "fix_stats",
            "dry_run": dry_run,
            "fixed": fixed,
            "skipped": skipped,
            "message": f"修复完成: {fixed} 个文档已更新, {skipped} 个跳过",
            "details": details,
        }

    @staticmethod
    def repair(kb_id: str) -> Dict[str, Any]:
        """
        修复知识库一致性

        修正 documents 表的 chunk_count 统计（安全操作，不删数据）
        """
        return ConsistencyService.fix_doc_stats(kb_id)

    @staticmethod
    def get_embedding_stats(kb_id: str) -> Dict[str, Any]:
        """
        获取 chunk 向量化统计信息

        Returns:
            {
                "kb_id": str,
                "total": int,        # 总 chunk 数
                "success": int,      # 成功向量化的 chunk 数 (embedding_generated=1)
                "failed": int,       # 向量化失败的 chunk 数 (embedding_generated=2)
                "pending": int,      # 等待向量化的 chunk 数 (embedding_generated=0)
                "lance_rows": int,   # LanceDB 实际行数
                "missing_count": int,  # LanceDB 缺少的数量
                "orphan_count": int,   # LanceDB 多余的数量
            }
        """
        from .database import init_chunk_db

        chunk_db = init_chunk_db()
        stats = chunk_db.get_embedding_stats(kb_id)

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            lance_stats = vs.get_stats()
            lance_rows = (
                lance_stats.get("row_count", 0) if lance_stats.get("exists") else 0
            )
        except Exception:
            lance_rows = 0

        chunk_count_actual = stats["total"]
        missing_count = max(0, chunk_count_actual - lance_rows)
        orphan_count = max(0, lance_rows - chunk_count_actual)

        return {
            "kb_id": kb_id,
            "total": stats["total"],
            "success": stats["success"],
            "failed": stats["failed"],
            "pending": stats["pending"],
            "lance_rows": lance_rows,
            "missing_count": missing_count,
            "orphan_count": orphan_count,
        }

    @staticmethod
    def safe_delete_files(kb_id: str, sources: List[str]) -> Dict[str, Any]:
        """
        原子性删除文件（保证 documents 和 LanceDB 一致）

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

        from .database import init_document_db
        import lancedb

        doc_db = init_document_db()

        deleted_sources = 0
        for source in sources:
            try:
                doc = doc_db.get_by_source_path(kb_id, source)
                if doc:
                    doc_id = doc.get("id")
                    if doc_id:
                        from .document_chunk_service import (
                            DocumentChunkService,
                        )

                        svc = DocumentChunkService(kb_id)
                        svc.delete_document_cascade(doc_id, delete_lance=True)
                        deleted_sources += 1
            except Exception as e:
                logger.warning(f"删除文档记录失败 {source}: {e}")

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
    def repair_all() -> Dict[str, Any]:
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
        from kb_core.registry import KnowledgeBaseRegistry

        registry = KnowledgeBaseRegistry()
        kbs = registry.list()

        results = []
        repaired = 0
        failed = 0

        for kb in kbs:
            kb_id = kb.id
            try:
                result = ConsistencyService.repair(kb_id)
                results.append(result)
                if result.get("fixed", 0) > 0:
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

    @staticmethod
    def get_doc_embedding_stats(kb_id: str) -> List[Dict[str, Any]]:
        """获取每个文档的向量统计
        
        实际检查 LanceDB，获取每个文档的向量生成状态。
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            文档向量统计列表
        """
        from .database import init_chunk_db

        return init_chunk_db().get_doc_embedding_stats(kb_id)

    @staticmethod
    def check_and_mark_failed(kb_id: str) -> Dict[str, Any]:
        """检查并标记向量生成失败的 chunks
        
        检查所有 chunk 是否存在于 LanceDB，将不存在的标记为失败。
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            检查结果统计
        """
        from .database import init_chunk_db

        chunk_db = init_chunk_db()
        result = chunk_db.mark_chunks_missing_from_lance(kb_id)
        return {
            "kb_id": kb_id,
            "marked_failed": result["marked_failed"],
            "total_checked": result["total_checked"],
            "message": f"已标记 {result['marked_failed']} 个 chunk 为失败（检查了 {result['total_checked']} 个）",
        }
