from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from rag.config import get_settings
from rag.logger import get_logger
from rag.ollama_utils import (
    create_parallel_ollama_embedding,
)

logger = get_logger(__name__)

from .vector_store import VectorStoreService
from .knowledge_base import KnowledgeBaseService

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

            failed_ids = stats.get("failed_ids", [])
            if failed_ids:
                doc_svc = get_document_chunk_service(kb_id)
                doc_svc.mark_chunks_failed(failed_ids, error="embedding returned zero vector or failed during import")

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
        chunk_strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        hierarchical_chunk_sizes: Optional[List[int]] = None,
        cancel_event: Any = None,
        chunk_progress_callback: Any = None,
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
        from kb_processing.document_processor import DocumentProcessorConfig, ProcessingProgress

        if progress_callback:
            progress_callback(f"开始导入 Zotero 文献: {item_id}")

        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = vs.persist_dir or Path.home() / ".llamaindex" / "storage" / kb_id

        settings = get_settings()
        config = DocumentProcessorConfig(
            chunk_size=chunk_size or settings.chunk_size,
            chunk_strategy=chunk_strategy or settings.chunk_strategy,
            hierarchical_chunk_sizes=hierarchical_chunk_sizes or settings.hierarchical_chunk_sizes,
        )
        importer = ZoteroImporter(config=config, kb_id=kb_id)
        try:
            item_id_int = int(item_id)
            item = importer.get_item(item_id_int, prefix=prefix)
            if not item:
                raise ValueError(f"文献不存在: {item_id}")

            progress = ProcessingProgress()

            force_ocr = options.get("force_ocr", False) if options else False
            is_scanned_override = options.get("is_scanned") if options else None
            has_md_cache = options.get("has_md_cache") if options else None

            logger.info(
                f"[ZoteroService.import_item] item_id={item_id}, prefix={prefix}, file_path={item.file_path}, force_ocr={force_ocr}, is_scanned_override={is_scanned_override}, has_md_cache={has_md_cache}"
            )
            nodes, all_nodes, processed_sources, error_reason, failed_ids = importer.import_item(
                item=item,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=progress,
                kb_id=kb_id,
                force_ocr=force_ocr,
                is_scanned=is_scanned_override,
                has_md_cache=has_md_cache,
                cancel_event=cancel_event,
                progress_callback=chunk_progress_callback,
            )

            if failed_ids:
                doc_svc = get_document_chunk_service(kb_id)
                doc_svc.mark_chunks_failed(failed_ids, error="embedding returned zero vector or failed during import")

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
