"""
Zotero 文档导入处理器

专门处理 Zotero 文献库：
- 文献元数据
- 标注和笔记
- PDF 附件（含扫描件检测和 OCR）
- Office 文档附件
"""

import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document as LlamaDocument
from llamaindex_study.node_parser import get_node_parser
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

from kb.document_processor import (
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
        dedup_manager=None,
    ):
        """
        初始化 Zotero 导入器

        Args:
            zotero_dir: Zotero 数据目录（默认 ~/.Zotero）
            db_path: Zotero 数据库路径
            config: 文档处理器配置
            dedup_manager: 可选的去重管理器，用于增量导入
        """
        self.zotero_dir = zotero_dir or Path.home() / "Zotero"
        self.db_path = db_path or self.zotero_dir / "zotero.sqlite"
        self.storage_dir = self.zotero_dir / "storage"

        self.processor = DocumentProcessor(config=config)
        self.dedup_manager = dedup_manager

        self._conn = None

    def connect(self):
        """连接数据库"""
        if not self._conn:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def _get_attachment_path(self, item_id: int) -> Optional[str]:
        """获取附件文件路径

        根据 Zotero UI 中修改的附件标题(fieldID=1)来判断是否包含 [kb] 标记，
        而非检查实际文件名。

        支持两种附件类型：
        - 独立附件：itemID 本身就是要查询的附件 ID
        - 子附件：需要通过 parentItemID 查找父 item 下的附件

        重要：必须严格只处理包含 [kb] 标记的附件，没有 [kb] 标记的附件会被跳过。
        """
        conn = self.connect()
        cursor = conn.cursor()

        # 只查找包含 [kb] 标记的附件，不再回退到其他附件
        cursor.execute(
            """
            SELECT ia.itemID, ia.path, ia.storageHash, ia.contentType, v.value as attachment_title
            FROM itemAttachments ia
            JOIN itemData d ON d.itemID = ia.itemID AND d.fieldID = 1
            JOIN itemDataValues v ON d.valueID = v.valueID
            WHERE (ia.itemID = ? OR ia.parentItemID = ?)
            AND v.value LIKE '%[kb]%'
            LIMIT 1
        """,
            (item_id, item_id),
        )
        row = cursor.fetchone()

        if not row or not row["path"]:
            return None

        title = row["attachment_title"] if row["attachment_title"] else ""
        # 严格检查：必须有 [kb] 标记
        if "[kb]" not in title:
            return None

        storage_hash = row["storageHash"]
        path = row["path"]

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

        if storage_hash:
            hash_dir = self.storage_dir / storage_hash
            if hash_dir.exists():
                for f in hash_dir.iterdir():
                    if f.is_file():
                        return str(f)

        if path.startswith("storage:"):
            filename = path.replace("storage:", "")

            for item_dir in self.storage_dir.iterdir():
                if not item_dir.is_dir() or item_dir.name.startswith("."):
                    continue

                check = item_dir / filename
                if check.exists():
                    return str(check)

                for f in item_dir.iterdir():
                    if f.is_file() and filename == f.name:
                        return str(f)

            full_path = self.storage_dir / filename
            if full_path.exists():
                return str(full_path)

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

        # 获取收藏夹中的文献
        placeholders = ",".join(["?"] * len(collection_ids))
        cursor.execute(
            f"""
            SELECT itemID FROM collectionItems
            WHERE collectionID IN ({placeholders})
        """,
            collection_ids,
        )

        return [row[0] for row in cursor.fetchall()]

    def get_item(self, item_id: int) -> Optional[ZoteroItem]:
        """
        获取文献详情

        Args:
            item_id: 文献 ID

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
        item.file_path = self._get_attachment_path(item_id)

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
    ) -> Tuple[int, List[Any]]:
        """
        导入单个文献

        Args:
            item: ZoteroItem
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录

        Returns:
            (生成的节点数, 所有节点列表)
        """
        from kb.zotero_reader import create_zotero_reader

        self.processor.set_embed_model(embed_model)
        node_parser = get_node_parser(
            chunk_size=self.processor.config.chunk_size,
            chunk_overlap=self.processor.config.chunk_overlap,
        )

        total_nodes = 0
        all_nodes = []
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
                total_nodes += self.processor.save_nodes(vector_store, nodes, progress)
                all_nodes.extend(nodes)

        if item.annotations or item.notes:
            logger.debug(
                f"文献包含标注/笔记: {item.title}, 标注数: {len(item.annotations)}, 笔记数: {len(item.notes)}"
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
                for doc in docs:
                    nodes = node_parser.get_nodes_from_documents([doc])
                    total_nodes += self.processor.save_nodes(
                        vector_store, nodes, progress
                    )
                    all_nodes.extend(nodes)
            else:
                logger.warning(f"文档处理返回空结果: {file_path}")

        return total_nodes, all_nodes

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

        Returns:
            导入统计
        """
        logger.info(f"开始导入 Zotero 收藏夹: {collection_name} (ID: {collection_id})")

        if rebuild and self.dedup_manager:
            logger.info("重建模式：清空去重状态")
            self.dedup_manager.clear()

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

            if self.dedup_manager:
                doc_id = f"zotero_{item_id}"
                existing = self.dedup_manager.get_record_by_doc_id(doc_id)
                if existing and not rebuild:
                    logger.debug(f"跳过已处理文献(dedup): {item_id}")
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
                total_nodes, all_nodes = self.import_item(
                    item, vector_store, embed_model, progress
                )
                if total_nodes > 0:
                    stats["nodes"] += total_nodes
                    stats["items"] += 1
                    if item.file_path:
                        stats["processed_sources"].append(item.file_path)
                    logger.info(f"文献导入成功: {item.title}, 节点数: {total_nodes}")

                    if self.dedup_manager:
                        self.dedup_manager.mark_processed(
                            file_path=Path(item.file_path)
                            if item.file_path
                            else Path(str(item_id)),
                            content=f"zotero_{item_id}_{item.title}",
                            doc_id=f"zotero_{item_id}",
                            chunk_count=total_nodes,
                            nodes=all_nodes,
                        )

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

        if self.dedup_manager:
            self.dedup_manager._save()
            logger.debug("去重状态已保存")

        logger.info(
            f"收藏夹导入完成: {collection_name}, "
            f"成功: {stats['items']}, 失败: {stats['failed']}, "
            f"节点: {stats['nodes']}"
        )

        return stats
