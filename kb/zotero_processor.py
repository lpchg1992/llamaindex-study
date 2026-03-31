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
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document as LlamaDocument
from llamaindex_study.node_parser import get_node_parser

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
    """

    def __init__(
        self,
        zotero_dir: Optional[Path] = None,
        db_path: Optional[Path] = None,
        config: Optional[DocumentProcessorConfig] = None,
    ):
        """
        初始化 Zotero 导入器

        Args:
            zotero_dir: Zotero 数据目录（默认 ~/.Zotero）
            db_path: Zotero 数据库路径
            config: 文档处理器配置
        """
        self.zotero_dir = zotero_dir or Path.home() / "Zotero"
        self.db_path = db_path or self.zotero_dir / "zotero.sqlite"
        self.storage_dir = self.zotero_dir / "storage"

        self.processor = DocumentProcessor(config=config)

        # 缓存
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
        """获取附件文件路径"""
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT path, storageHash, contentType
            FROM itemAttachments
            WHERE parentItemID = ?
            LIMIT 1
        """,
            (item_id,),
        )
        row = cursor.fetchone()

        if not row or not row["path"]:
            return None

        storage_hash = row["storageHash"]
        path = row["path"]

        # 检查是否是 PDF 或其他可读格式
        content_type = row["contentType"] or ""
        supported = any(
            ext in content_type
            for ext in ["pdf", "document", "presentation", "spreadsheet"]
        )

        if not supported:
            return None

        # 方法1: 如果有 storageHash，用 hash 目录
        if storage_hash:
            hash_dir = self.storage_dir / storage_hash
            if hash_dir.exists():
                for f in hash_dir.iterdir():
                    if f.is_file():
                        return str(f)

        # 方法2: 从 path 中提取文件名
        if path.startswith("storage:"):
            filename = path.replace("storage:", "")
            full_path = self.storage_dir / filename
            if full_path.exists():
                return str(full_path)

            # 在子目录中查找
            for item_dir in self.storage_dir.iterdir():
                if item_dir.is_dir():
                    full_path = item_dir / filename
                    if full_path.exists():
                        return str(full_path)

                    # 也检查子目录下的文件
                    for f in item_dir.rglob("*"):
                        if f.is_file() and filename in f.name:
                            return str(f)

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
    ) -> int:
        """
        导入单个文献

        Args:
            item: ZoteroItem
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录

        Returns:
            生成的节点数
        """
        from kb.zotero_reader import create_zotero_reader

        self.processor.set_embed_model(embed_model)
        node_parser = get_node_parser(
            chunk_size=self.processor.config.chunk_size,
            chunk_overlap=self.processor.config.chunk_overlap,
        )

        total_nodes = 0
        creators_str = ", ".join(item.creators) if item.creators else ""
        base_metadata = {
            "item_id": item.item_id,
            "title": item.title,
            "creators": creators_str,
            "tags": ", ".join(item.tags),
        }

        # 1. 处理标注/笔记
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

        # 2. 处理附件
        if item.file_path and Path(item.file_path).exists():
            file_path = Path(item.file_path)
            ext = file_path.suffix.lower()

            print(
                f"   📄 {item.title[:40]}... ({file_path.stat().st_size / 1024 / 1024:.1f}MB)"
            )

            if ext == ".pdf":
                docs = self.processor.process_pdf(
                    str(file_path),
                    metadata=base_metadata,
                )
            elif ext in [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".md", ".txt"]:
                docs = self.processor.process_document(
                    str(file_path),
                    metadata=base_metadata,
                )
            else:
                docs = []

            if docs:
                for doc in docs:
                    nodes = node_parser.get_nodes_from_documents([doc])
                    total_nodes += self.processor.save_nodes(
                        vector_store, nodes, progress
                    )

        return total_nodes

    def import_collection(
        self,
        collection_id: int,
        collection_name: str,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        rebuild: bool = False,
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

        Returns:
            导入统计
        """
        print(f"\n{'=' * 60}")
        print(f"📚 Zotero: {collection_name}")
        print(f"{'=' * 60}")

        # 获取文献列表
        item_ids = self.get_items_in_collection(collection_id)
        print(f"   共 {len(item_ids)} 篇文献")

        if not item_ids:
            return {"items": 0, "nodes": 0, "failed": 0}

        if progress:
            progress.total_items = len(item_ids)
            if not progress.started_at:
                progress.started_at = time.time()

        processed_set = set(progress.processed_items) if progress else set()

        stats = {"items": 0, "nodes": 0, "failed": 0}

        for i, item_id in enumerate(item_ids):
            if str(item_id) in processed_set:
                continue

            if i % 5 == 0:
                elapsed = time.time() - (
                    progress.started_at if progress else time.time()
                )
                print(
                    f"\n   进度: {i + 1}/{len(item_ids)} ({100 * (i + 1) // len(item_ids)}%)"
                )
                print(f"   节点: {stats['nodes']}, 耗时: {elapsed:.0f}s")

            item = self.get_item(item_id)
            if not item:
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(str(item_id))
                continue

            try:
                nodes = self.import_item(item, vector_store, embed_model, progress)
                stats["nodes"] += nodes
                stats["items"] += 1
            except Exception as e:
                print(f"   ⚠️  导入失败: {item.title[:40]} - {e}")
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(str(item_id))

            if progress:
                progress.processed_items.append(str(item_id))
                progress.save(Path.home() / ".llamaindex" / "zotero_progress.json")

        return stats
