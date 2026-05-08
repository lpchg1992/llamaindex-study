"""
Zotero 文档导入处理器

专门处理 Zotero 文献库：
- 文献元数据
- 标注和笔记
- PDF 附件（含扫描件检测和 OCR）
- Office 文档附件
"""

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from llama_index.core.schema import Document as LlamaDocument
from rag.logger import get_logger

logger = get_logger(__name__)

from kb_processing.document_processor import (
    DocumentProcessor,
    DocumentProcessorConfig,
    ProcessingProgress,
)


@dataclass
class ZoteroItem:
    """Zotero 文献项"""

    item_id: int
    title: str
    creators: List[str] = field(default_factory=list)
    file_path: Optional[str] = None
    annotations: List[dict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class ZoteroImporter:
    """
    Zotero 文献导入器

    功能：
    - 获取收藏夹中的文献列表
    - 读取文献元数据、标注、笔记
    - 处理 PDF 附件（含 OCR）
    - 处理 Office 文档附件
    - 增量导入和断点续传
    - 去重支持（基于 item_id）
    """

    def __init__(
        self,
        zotero_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        config: Optional[DocumentProcessorConfig] = None,
        kb_id: Optional[str] = None,
    ):
        self.zotero_dir = zotero_dir or Path.home() / "Zotero"
        self.db_path = db_path or self.zotero_dir / "zotero.sqlite"
        self.storage_dir = self.zotero_dir / "storage"

        self.processor = DocumentProcessor(config=config)
        self.kb_id = kb_id

        self._conn = None

    def connect(self):
        """连接数据库（优先读写模式，数据库被锁定时降级为只读模式）"""
        if not self._conn:
            db_path = str(self.db_path)
            try:
                # 优先尝试读写模式
                self._conn = sqlite3.connect(db_path)
                self._conn.row_factory = sqlite3.Row
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    # 数据库被锁定，尝试只读模式
                    try:
                        self._conn = sqlite3.connect(
                            f"file:{db_path}?mode=ro", uri=True
                        )
                        self._conn.row_factory = sqlite3.Row
                    except sqlite3.OperationalError:
                        # 仍然失败，尝试使用备份文件
                        backup_path = f"{db_path}.bak"
                        self._conn = sqlite3.connect(
                            f"file:{backup_path}?mode=ro", uri=True
                        )
                        self._conn.row_factory = sqlite3.Row
                else:
                    raise
        return self._conn

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _get_attachment_path(self, item_id: int, prefix: str = "[kb]") -> Optional[str]:
        """获取附件文件路径

        Zotero 存储机制：
        - 附件存储在 {zotero_dir}/storage/{item_key}/{filename} 目录下
        - item_key 是 items 表中的 key 字段，不是 storageHash
        - storageHash 是文件内容哈希，用于去重，不代表目录名

        Args:
            item_id: Zotero 文献 ID
            prefix: 附件标题前缀标记（默认 [kb]）
        """
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT ia.itemID, ia.path, ia.contentType, i.key as item_key, v.value as attachment_title
            FROM itemAttachments ia
            JOIN items i ON ia.itemID = i.itemID
            JOIN itemData d ON d.itemID = ia.itemID AND d.fieldID = 1
            JOIN itemDataValues v ON d.valueID = v.valueID
            WHERE (ia.itemID = ? OR ia.parentItemID = ?)
            AND v.value LIKE ?
            LIMIT 1
        """,
            (item_id, item_id, f"%{prefix}%"),
        )
        row = cursor.fetchone()

        if not row or not row["path"]:
            return None

        title = row["attachment_title"] if row["attachment_title"] else ""
        if prefix not in title:
            return None

        path = row["path"]
        item_key = row["item_key"]
        content_type = row["contentType"] or ""

        supported = any(
            ext in content_type
            for ext in [
                "pdf",
                "document",
                "presentation",
                "spreadsheet",
                "ms-excel",
                "excel",
                "msword",
                "wordprocessingml",
            ]
        )

        if not supported:
            return None

        if path.startswith("storage:") and item_key:
            filename = path.replace("storage:", "")
            # 正确的路径：{storage_dir}/{item_key}/{filename}
            correct_path = self.storage_dir / item_key / filename
            if correct_path.exists():
                return str(correct_path)

        return None

    def get_collections(self) -> List[dict]:
        """获取所有收藏夹"""
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT collectionID, collectionName, parentCollectionID
            FROM collections
            WHERE libraryID = 1
            ORDER BY collectionName
        """)
        return [dict(row) for row in cursor.fetchall()]

    def get_collection_by_name(self, name: str) -> Optional[dict]:
        """
        根据收藏夹名称查找收藏夹

        Args:
            name: 收藏夹名称（支持模糊匹配）

        Returns:
            收藏夹信息 dict 或 None
        """
        conn = self.connect()
        cursor = conn.cursor()

        # 精确匹配
        cursor.execute(
            """
            SELECT collectionID, collectionName, parentCollectionID
            FROM collections
            WHERE libraryID = 1 AND collectionName = ?
        """,
            (name,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "collectionID": row[0],
                "collectionName": row[1],
                "parentCollectionID": row[2],
            }

        # 模糊匹配（包含）
        cursor.execute(
            """
            SELECT collectionID, collectionName, parentCollectionID
            FROM collections
            WHERE libraryID = 1 AND collectionName LIKE ?
            LIMIT 5
        """,
            (f"%{name}%",),
        )

        results = cursor.fetchall()
        if len(results) == 1:
            row = results[0]
            return {
                "collectionID": row[0],
                "collectionName": row[1],
                "parentCollectionID": row[2],
            }
        elif len(results) > 1:
            # 返回多个匹配结果
            return {
                "multiple": True,
                "matches": [
                    {"collectionID": r[0], "collectionName": r[1]} for r in results
                ],
            }

        return None

    def get_items_in_collection(
        self,
        collection_id: int,
        recursive: bool = True,
    ) -> List[int]:
        """
        获取收藏夹中的文献 ID 列表

        Args:
            collection_id: 收藏夹 ID
            recursive: 是否包含子收藏夹

        Returns:
            文献 item ID 列表
        """
        conn = self.connect()
        cursor = conn.cursor()

        # 获取所有子收藏夹
        collection_ids = [collection_id]
        if recursive:
            cursor.execute(
                """
                WITH RECURSIVE sub_collections AS (
                    SELECT collectionID FROM collections WHERE parentCollectionID = ?
                    UNION ALL
                    SELECT c.collectionID FROM collections c
                    JOIN sub_collections sc ON c.parentCollectionID = sc.collectionID
                )
                SELECT collectionID FROM sub_collections
            """,
                (collection_id,),
            )
            collection_ids.extend([row[0] for row in cursor.fetchall()])

        # 获取收藏夹中的文献（使用 DISTINCT 去重）
        placeholders = ",".join(["?"] * len(collection_ids))
        cursor.execute(
            f"""
            SELECT DISTINCT itemID FROM collectionItems
            WHERE collectionID IN ({placeholders})
        """,
            collection_ids,
        )

        return [row[0] for row in cursor.fetchall()]

    def get_item(self, item_id: int, prefix: str = "[kb]") -> Optional[ZoteroItem]:
        """
        获取文献详情

        Args:
            item_id: 文献 ID
            prefix: 附件标题前缀标记

        Returns:
            ZoteroItem 或 None
        """
        conn = self.connect()
        cursor = conn.cursor()

        # 获取基本信息
        cursor.execute(
            """
            SELECT i.itemID, t.typeName as item_type
            FROM items i
            JOIN itemTypes t ON i.itemTypeID = t.itemTypeID
            WHERE i.itemID = ? AND i.libraryID = 1
        """,
            (item_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # 获取标题 (fieldID = 1)
        cursor.execute(
            """
            SELECT v.value
            FROM itemData d
            JOIN itemDataValues v ON d.valueID = v.valueID
            WHERE d.itemID = ? AND d.fieldID = 1
        """,
            (item_id,),
        )
        title_row = cursor.fetchone()
        title = title_row["value"] if title_row else "Untitled"

        item = ZoteroItem(
            item_id=row["itemID"],
            title=title,
        )

        # 获取作者
        cursor.execute(
            """
            SELECT c.firstName, c.lastName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
        """,
            (item_id,),
        )
        for creator_row in cursor.fetchall():
            if creator_row["firstName"] or creator_row["lastName"]:
                name = f"{creator_row['firstName'] or ''} {creator_row['lastName'] or ''}".strip()
                item.creators.append(name)

        # 获取标签
        cursor.execute(
            """
            SELECT name FROM tags
            JOIN itemTags ON tags.tagID = itemTags.tagID
            WHERE itemTags.itemID = ?
        """,
            (item_id,),
        )
        item.tags = [row[0] for row in cursor.fetchall()]

        # 获取附件路径
        item.file_path = self._get_attachment_path(item_id, prefix=prefix)

        # 获取标注
        cursor.execute(
            """
            SELECT text, comment, color
            FROM itemAnnotations
            WHERE parentItemID = ?
            ORDER BY sortIndex ASC
        """,
            (item_id,),
        )
        for ann_row in cursor.fetchall():
            item.annotations.append(
                {
                    "text": ann_row["text"] or "",
                    "comment": ann_row["comment"] or "",
                    "color": ann_row["color"] or "",
                }
            )

        # 获取笔记
        cursor.execute(
            """
            SELECT note, title
            FROM itemNotes
            WHERE parentItemID = ?
        """,
            (item_id,),
        )
        for note_row in cursor.fetchall():
            if note_row["note"]:
                item.notes.append(note_row["note"])

        return item

    def import_item(
        self,
        item: ZoteroItem,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        kb_id: Optional[str] = None,
        force_ocr: bool = False,
        is_scanned: Optional[bool] = None,
        has_md_cache: Optional[bool] = None,
        cancel_event: Any = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[int, List[Any], List[str], Optional[str], List[str]]:
        """
        导入单个文献

        Args:
            item: ZoteroItem
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录
            kb_id: 知识库 ID（用于写入 document 表）
            force_ocr: 强制 OCR 处理
            is_scanned: 预计算的扫描件判断（用户可覆盖）
            has_md_cache: 是否有 MD 缓存（前端传递，避免重复检测）

        Returns:
            (生成的节点数, 所有节点列表, 处理过的源文件路径列表, 错误原因, 失败的节点ID列表)
        """
        from kb_zotero.reader import create_zotero_reader
        from kb_core.document_chunk_service import get_document_chunk_service

        self.processor.set_embed_model(embed_model)
        node_parser = self.processor.get_node_parser()

        effective_kb_id = kb_id or self.kb_id or "default"
        doc_chunk_service = get_document_chunk_service(effective_kb_id)

        total_nodes = 0
        all_nodes = []
        processed_sources = []
        all_failed_ids = []
        creators_str = ", ".join(item.creators) if item.creators else ""
        base_metadata = {
            "item_id": item.item_id,
            "title": item.title,
            "creators": creators_str,
            "tags": ", ".join(item.tags),
        }

        if item.annotations or item.notes:
            text_parts = [f"# {item.title}"]
            if item.creators:
                text_parts.append(f"作者: {', '.join(item.creators)}")

            if item.annotations:
                text_parts.append("\n## 标注:")
                for ann in item.annotations:
                    text_parts.append(f"- {ann['text']}")
                    if ann["comment"]:
                        text_parts.append(f"  注: {ann['comment']}")

            if item.notes:
                text_parts.append("\n## 笔记:")
                for note in item.notes:
                    text_parts.append(note)

            text = "\n".join(text_parts)
            if len(text.strip()) >= 50:
                doc = LlamaDocument(
                    text=text,
                    metadata={
                        "source": "zotero_meta",
                        **base_metadata,
                    },
                    id_=f"zotero_meta_{item.item_id}",
                )
                nodes = node_parser.get_nodes_from_documents([doc])

                # Generate embeddings before upsert
                texts = [node.get_content() for node in nodes]
                embeddings_generated = False
                failed_ids = []
                error_reason = None
                MAX_TEXT_LEN = 8000
                for i, node in enumerate(nodes):
                    if cancel_event and cancel_event.is_set():
                        logger.warning(f"[{item.title}] 任务已取消，停止 embedding")
                        failed_ids.extend(n.node_id for n in nodes[i:])
                        break
                    text = texts[i]
                    text_len = len(text)
                    if text_len > MAX_TEXT_LEN:
                        text = text[:MAX_TEXT_LEN]
                        logger.warning(
                            f"[{item.title}] 标注/笔记文本过长被截断 (node={node.node_id[:8]}, orig_len={text_len}, truncated_to={MAX_TEXT_LEN})"
                        )
                    try:
                        ep = embed_model._get_best_endpoint()
                        ep_name, embedding, error = (
                            embed_model._get_embedding_with_retry(text, ep)
                        )
                        if error:
                            logger.warning(
                                f"[{item.title}] Embedding failed (endpoint={ep_name}, node={node.node_id[:8]}, text_len={text_len}): {error}"
                            )
                            failed_ids.append(node.node_id)
                        elif embedding is None or all(v == 0.0 for v in embedding):
                            logger.warning(
                                f"[{item.title}] Embedding returned {'None' if embedding is None else 'zero vector'} (endpoint={ep_name}, node={node.node_id[:8]}, text_len={text_len})"
                            )
                            failed_ids.append(node.node_id)
                        else:
                            node.embedding = embedding
                            embeddings_generated = True
                    except Exception as emb_err:
                        logger.error(
                            f"[{item.title}] Embedding exception (node={node.node_id[:8]}): {type(emb_err).__name__}: {emb_err}"
                        )
                        failed_ids.append(node.node_id)

                if not embeddings_generated and len(failed_ids) == len(nodes):
                    error_reason = f"所有 chunk embedding 失败 ({len(nodes)} 个节点)"
                    logger.warning(f"[{item.title}] zotero_meta: {error_reason}")

                if not error_reason and len(failed_ids) == len(nodes):
                    error_reason = (
                        f"所有 chunk embedding 失败或返回零向量 ({len(nodes)} 个节点)"
                    )
                    logger.warning(f"[{item.title}] zotero_meta: {error_reason}")

                all_failed_ids = list(set(failed_ids))
                meta_doc_id = f"zotero_meta_{item.item_id}"
                result = doc_chunk_service.create_document(
                    source_file=f"zotero_meta_{item.item_id}",
                    source_path=f"zotero://item/{item.item_id}",
                    file_hash="",
                    nodes=nodes,
                    file_size=len(text.encode("utf-8")),
                    doc_id=meta_doc_id,
                    zotero_doc_id=str(item.item_id),
                    failed_node_ids=all_failed_ids if all_failed_ids else None,
                )
                if not result:
                    logger.warning(f"zotero_meta 文档记录创建失败: {item.title}")
                else:
                    meta_node_ids = [n.node_id for n in nodes]
                    try:
                        success_count, written_ids, _, emb_failed_ids = (
                            self.processor._upsert_nodes(
                                vector_store._get_lance_vector_store(), nodes
                            )
                        )
                        if written_ids:
                            doc_chunk_service.mark_chunks_success(written_ids)
                        if emb_failed_ids:
                            doc_chunk_service.mark_chunks_failed(emb_failed_ids, error="embedding unavailable (missing or zero vector)")
                        all_failed_ids = list(set(all_failed_ids + failed_ids + emb_failed_ids))
                    except Exception as e:
                        logger.warning(
                            f"LanceDB 写入失败 (zotero_meta): {item.title}, 错误: {e}"
                        )
                        success_count = 0
                        error_reason = f"LanceDB write failed for zotero_meta: {e}"
                        doc_chunk_service.mark_chunks_failed(meta_node_ids, error=error_reason)
                        all_failed_ids = list(set(all_failed_ids + meta_node_ids))
                    total_nodes += len(nodes)
                    if success_count > 0:
                        all_nodes.extend(
                            [
                                n
                                for n in nodes
                                if hasattr(n, "embedding")
                                and n.embedding
                                and not all(v == 0.0 for v in n.embedding)
                            ]
                        )
                        processed_sources.append("zotero_meta")
            else:
                logger.debug(
                    f"[{item.title}] zotero_meta 跳过: 标注/笔记内容过短 ({len(text.strip())} 字符)"
                )

        if item.annotations or item.notes:
            logger.debug(
                f"文献包含标注/笔记: {item.title}, 标注数: {len(item.annotations)}, 笔记数: {len(item.notes)}"
            )

        logger.info(
            f"[ZoteroImporter.import_item] item_id={item.item_id}, title={item.title}, file_path={item.file_path}, is_scanned={is_scanned}, force_ocr={force_ocr}"
        )

        error_reason = None
        failed_ids = []
        if not item.file_path:
            error_reason = "附件路径未找到（Zotero 数据库中无附件记录）"
            logger.warning(
                f"[ZoteroImporter.import_item] file_path is None, skipping attachment processing"
            )
        elif not Path(item.file_path).exists():
            error_reason = f"附件文件不存在: {item.file_path}"
            logger.warning(
                f"[ZoteroImporter.import_item] file_path does not exist: {item.file_path}"
            )

        if item.file_path and Path(item.file_path).exists():
            file_path = Path(item.file_path)
            ext = file_path.suffix.lower()
            file_size_mb = file_path.stat().st_size / 1024 / 1024

            logger.info(
                f"处理附件: {item.title}, 类型: {ext}, 大小: {file_size_mb:.1f}MB"
            )

            if ext == ".pdf":
                logger.debug(f"使用 process_pdf 处理: {file_path}")
                docs = self.processor.process_pdf(
                    str(file_path),
                    metadata={**base_metadata, "source": str(file_path)},
                    force_ocr=force_ocr,
                    is_scanned=is_scanned,
                    has_md_cache=has_md_cache,
                )
            elif ext in [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".md", ".txt"]:
                logger.debug(f"使用 process_document 处理: {file_path}")
                docs = self.processor.process_document(
                    str(file_path),
                    metadata={**base_metadata, "source": str(file_path)},
                )
            else:
                logger.warning(f"不支持的文件类型: {ext}, 文件: {file_path}")
                docs = []

            if docs:
                for doc in docs:
                    doc.id_ = f"zotero_{item.item_id}_{file_path.stem}"
                logger.debug(f"文档处理完成, 文档数: {len(docs)}")

                file_hash = self.processor.compute_file_hash(str(file_path))
                file_size = file_path.stat().st_size

                for doc in docs:
                    nodes = node_parser.get_nodes_from_documents([doc])
                    if not nodes:
                        logger.warning(
                            f"节点解析返回空: {file_path}, doc文本长度: {len(doc.text)}"
                        )
                        continue
                    doc_id = doc.id_
                    zotero_doc_id = str(item.item_id)

                    # Phase 1: 先创建文档和 chunk 记录（emb_status=0），立即可查询
                    result = doc_chunk_service.create_document(
                        source_file=file_path.name,
                        source_path=str(file_path),
                        file_hash=file_hash,
                        nodes=nodes,
                        file_size=file_size,
                        doc_id=doc_id,
                        zotero_doc_id=zotero_doc_id,
                        failed_node_ids=None,
                    )
                    if not result:
                        logger.warning(f"文档记录创建失败: {file_path}")
                        continue

                    # 分块完成，立即通知 total_chunks
                    if progress_callback:
                        progress_callback(0, len(nodes))

                    total = len(nodes)
                    texts = [node.get_content() for node in nodes]
                    embeddings_generated = False
                    failed_ids = []
                    MAX_TEXT_LEN = 8000
                    MAX_CONCURRENT = 4

                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    import threading

                    processed_count = [0]

                    def embed_one(idx: int, node, text: str):
                        if cancel_event and cancel_event.is_set():
                            return idx, node, None, "已取消"
                        text_len = len(text)
                        if text_len > MAX_TEXT_LEN:
                            text = text[:MAX_TEXT_LEN]
                        ep = embed_model._get_best_endpoint()
                        ep_name, embedding, error = embed_model._get_embedding_with_retry(text, ep)
                        return idx, node, embedding, error or ep_name

                    for batch_start in range(0, total, MAX_CONCURRENT):
                        if cancel_event and cancel_event.is_set():
                            logger.warning(f"[{item.title}] 任务已取消，停止 embedding")
                            for i in range(batch_start, total):
                                failed_ids.append(nodes[i].node_id)
                            break

                        batch_end = min(batch_start + MAX_CONCURRENT, total)
                        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
                            futures = {}
                            for i in range(batch_start, batch_end):
                                text = texts[i]
                                text_len = len(text)
                                if text_len > MAX_TEXT_LEN:
                                    logger.warning(
                                        f"[{item.title}] 文本过长被截断 (file={file_path.name}, node={nodes[i].node_id[:8]}, orig_len={text_len}, truncated_to={MAX_TEXT_LEN})"
                                    )
                                futures[executor.submit(embed_one, i, nodes[i], texts[i])] = i

                            batch_nodes = []
                            for future in as_completed(futures):
                                idx, node, embedding, result_info = future.result()
                                if embedding is None or all(v == 0.0 for v in embedding):
                                    logger.warning(
                                        f"[{item.title}] Embedding failed or zero vector (file={file_path.name}, node={node.node_id[:8]}, text_len={len(texts[idx])}): {result_info}"
                                    )
                                    failed_ids.append(node.node_id)
                                else:
                                    node.embedding = embedding
                                    embeddings_generated = True
                                    batch_nodes.append(node)
                                processed_count[0] += 1
                                if progress_callback:
                                    progress_callback(processed_count[0], total)

                            # 每批嵌入后立即写入 LanceDB 并更新 SQLite 状态
                            if batch_nodes:
                                try:
                                    b_success, b_written_ids, _, b_failed = (
                                        self.processor._upsert_nodes(
                                            vector_store._get_lance_vector_store(), batch_nodes
                                        )
                                    )
                                    if b_failed:
                                        doc_chunk_service.mark_chunks_failed(b_failed, error="embedding unavailable (missing or zero vector)")
                                        all_failed_ids = list(set(all_failed_ids + b_failed))
                                    if b_success < len(batch_nodes):
                                        logger.warning(
                                            f"LanceDB 批次部分写入: 预期 {len(batch_nodes)}, 实际 {b_success}"
                                        )
                                    if b_written_ids:
                                        doc_chunk_service.mark_chunks_success(b_written_ids)
                                        total_nodes += b_success
                                        all_nodes.extend([n for n in batch_nodes if n.node_id in b_written_ids])
                                        if not processed_sources or processed_sources[-1] != str(file_path):
                                            processed_sources.append(str(file_path))
                                except Exception as e:
                                    logger.warning(f"LanceDB 批次写入失败: {file_path}, 错误: {e}")
                                    failed_node_ids = list(set(failed_ids + [n.node_id for n in batch_nodes]))
                                    doc_chunk_service.mark_chunks_failed(failed_node_ids, error=f"LanceDB batch write failed: {e}")
                                    all_failed_ids = list(set(all_failed_ids + failed_node_ids))
                                    total_nodes += len(batch_nodes)
            else:
                logger.warning(f"文档处理返回空结果: {file_path}")

        if failed_ids:
            doc_chunk_service.mark_chunks_failed(
                failed_ids, error="embedding failed or returned zero vector"
            )
            all_failed_ids = list(set(all_failed_ids + failed_ids))
            logger.warning(
                f"[{item.title}] {len(failed_ids)} chunks embedding failed, marked as failed in SQLite"
            )

        return total_nodes, all_nodes, processed_sources, error_reason, all_failed_ids

    def import_collection(
        self,
        collection_id: int,
        collection_name: str,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        rebuild: bool = False,
        progress_file: Path = None,
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
        cancel_event: Optional["threading.Event"] = None,
        kb_id: Optional[str] = None,
    ) -> dict:
        """
        导入整个收藏夹

        Args:
            collection_id: 收藏夹 ID
            collection_name: 收藏夹名称（用于显示）
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录
            rebuild: 是否重建
            progress_file: 进度保存路径
            progress_callback: 进度回调 (current, total, message, level)
            cancel_event: 取消事件，用于主动终止
            kb_id: 知识库 ID（用于写入 document 表）

        Returns:
            导入统计
        """
        logger.info(f"开始导入 Zotero 收藏夹: {collection_name} (ID: {collection_id})")

        item_ids = self.get_items_in_collection(collection_id)
        logger.info(f"收藏夹包含 {len(item_ids)} 篇文献")

        if not item_ids:
            logger.warning(f"收藏夹为空: {collection_name}")
            return {"items": 0, "nodes": 0, "failed": 0}

        if progress:
            progress.total_items = len(item_ids)
            if not progress.started_at:
                progress.started_at = time.time()

        processed_set = set(progress.processed_items) if progress else set()
        logger.debug(f"已有 {len(processed_set)} 篇文献已处理，跳过")

        stats = {"items": 0, "nodes": 0, "failed": 0, "processed_sources": []}

        for i, item_id in enumerate(item_ids):
            if cancel_event and cancel_event.is_set():
                logger.info(f"导入被取消，已处理 {stats['items']} 篇文献")
                break

            item_id_str = str(item_id)
            if item_id_str in processed_set:
                logger.debug(f"跳过已处理文献: {item_id}")
                continue

            if not rebuild:
                from kb_core.database import init_document_db

                doc_db = init_document_db()
                existing = doc_db.get_by_zotero_doc_id(kb_id, str(item_id))
                if existing:
                    logger.debug(f"跳过已处理文献(document): {item_id}")
                    continue

            if i % 5 == 0:
                elapsed = time.time() - (
                    progress.started_at if progress else time.time()
                )
                msg = f"进度: {i + 1}/{len(item_ids)}, 节点: {stats['nodes']}, 耗时: {elapsed:.0f}s"
                logger.info(msg)
                if progress_callback:
                    progress_callback(i + 1, len(item_ids), msg, "info")

            item = self.get_item(item_id)
            if not item:
                logger.warning(f"文献不存在或已删除: item_id={item_id}")
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(item_id_str)
                continue

            logger.debug(f"处理文献: {item.title} (item_id={item_id})")

            try:
                total_nodes, all_nodes, _, _, item_failed_ids = self.import_item(
                    item, vector_store, embed_model, progress, kb_id=kb_id
                )
                if item_failed_ids:
                    stats.setdefault("failed_ids", []).extend(item_failed_ids)
                if total_nodes > 0:
                    stats["nodes"] += total_nodes
                    stats["items"] += 1
                    if item.file_path:
                        stats["processed_sources"].append(item.file_path)
                    logger.info(f"文献导入成功: {item.title}, 节点数: {total_nodes}")

                    if progress:
                        progress.processed_items.append(item_id_str)
                        save_path = (
                            progress_file
                            or Path.home() / ".llamaindex" / "zotero_progress.json"
                        )
                        progress.save(save_path)
                else:
                    logger.warning(f"文献未产生节点: {item.title}")

            except Exception as e:
                logger.error(f"文献导入失败: {item.title}, 错误: {e}")
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(item_id_str)

        logger.info(
            f"收藏夹导入完成: {collection_name}, "
            f"成功: {stats['items']}, 失败: {stats['failed']}, "
            f"节点: {stats['nodes']}"
        )

        failed_ids = stats.pop("failed_ids", [])
        if failed_ids:
            doc_svc = get_document_chunk_service(kb_id or self.kb_id or "default")
            doc_svc.mark_chunks_failed(failed_ids, error="embedding returned zero vector or failed during import")

        return stats
