"""
Zotero 文档读取器

从 Zotero 数据库中提取文献元数据、PDF、标注和笔记。
支持：
- 从本地 SQLite 数据库读取
- 提取 PDF 标注/高亮
- 提取笔记
- 获取文献元数据
- 按收藏夹分类
"""

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from llama_index.core.schema import Document as LlamaDocument


# Zotero 默认数据目录
DEFAULT_ZOTERO_DATA_DIR = Path.home() / "Zotero"


@dataclass
class ZoteroItem:
    """Zotero 文献条目"""
    item_id: int
    key: str
    title: str
    item_type: str
    creators: List[str] = field(default_factory=list)
    abstract: str = ""
    date: str = ""
    tags: List[str] = field(default_factory=list)
    collections: List[str] = field(default_factory=list)
    doi: str = ""
    url: str = ""
    publisher: str = ""
    publication_title: str = ""
    journal_abbreviation: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    file_path: Optional[str] = None
    annotations: List[Dict] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        """转换为可检索的文本"""
        parts = [
            f"# {self.title}",
            f"类型: {self.item_type}",
            f"作者: {', '.join(self.creators) if self.creators else '未知'}",
            f"日期: {self.date}",
        ]
        if self.abstract:
            parts.append(f"\n摘要:\n{self.abstract}")
        if self.tags:
            parts.append(f"\n标签: {', '.join(self.tags)}")
        if self.annotations:
            parts.append("\n## 标注内容:")
            for ann in self.annotations:
                parts.append(f"- {ann.get('text', '')}")
                if ann.get('comment'):
                    parts.append(f"  注: {ann['comment']}")
        if self.notes:
            parts.append("\n## 笔记:")
            for note in self.notes:
                parts.append(f"- {note}")
        return "\n".join(parts)


class ZoteroReader:
    """
    Zotero 文档加载器

    从 Zotero SQLite 数据库中读取文献、标注和笔记。
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        include_annotations: bool = True,
        include_notes: bool = True,
        include_pdf_text: bool = False,
    ):
        """
        初始化 Zotero 读取器

        Args:
            data_dir: Zotero 数据目录（默认 ~/.Zotero）
            include_annotations: 是否提取标注
            include_notes: 是否提取笔记
            include_pdf_text: 是否提取 PDF 文本内容
        """
        self.data_dir = data_dir or DEFAULT_ZOTERO_DATA_DIR
        self.db_path = self.data_dir / "zotero.sqlite"
        self.storage_dir = self.data_dir / "storage"
        self.include_annotations = include_annotations
        self.include_notes = include_notes
        self.include_pdf_text = include_pdf_text

        if not self.db_path.exists():
            raise FileNotFoundError(f"Zotero 数据库未找到: {self.db_path}")

        self._conn: Optional[sqlite3.Connection] = None

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_collections(self) -> List[Dict]:
        """
        获取所有收藏夹

        Returns:
            收藏夹列表 [{id, name, parent_id}, ...]
        """
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT collectionID, collectionName, parentCollectionID
            FROM collections
            ORDER BY collectionName
        """)
        return [
            {"id": row["collectionID"], "name": row["collectionName"], "parent_id": row["parentCollectionID"]}
            for row in cursor.fetchall()
        ]

    def get_collection_tree(self, root_id: int = None) -> Dict:
        """
        获取收藏夹树结构

        Args:
            root_id: 根收藏夹 ID，None 表示获取全部

        Returns:
            嵌套的收藏夹字典
        """
        collections = self.get_collections()
        collection_map = {c["id"]: {**c, "children": []} for c in collections}

        result = []
        for c in collections:
            if c["parent_id"] == root_id:
                result.append(collection_map[c["id"]])

        def add_children(node):
            for c in collections:
                if c["parent_id"] == node["id"]:
                    child = collection_map[c["id"]]
                    node["children"].append(child)
                    add_children(child)

        for node in result:
            add_children(node)

        return result if root_id is None else result[0] if result else {}

    def _get_item_field(self, item_id: int, field_name: str) -> Optional[str]:
        """获取文献的指定字段"""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT v.value
            FROM itemData d
            JOIN itemDataValues v ON d.valueID = v.valueID
            JOIN fields f ON d.fieldID = f.fieldID
            WHERE d.itemID = ? AND f.fieldName = ?
        """, (item_id, field_name))
        result = cursor.fetchone()
        return result["value"] if result else None

    def _get_item_creators(self, item_id: int) -> List[str]:
        """获取文献的作者"""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT cr.firstName, cr.lastName, ic.creatorTypeID
            FROM itemCreators ic
            JOIN creators cr ON ic.creatorID = cr.creatorID
            WHERE ic.itemID = ?
        """, (item_id,))
        creators = []
        for row in cursor.fetchall():
            name = f"{row['firstName']} {row['lastName']}".strip()
            if name:
                creators.append(name)
        return creators

    def _get_item_tags(self, item_id: int) -> List[str]:
        """获取文献的标签"""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT t.name
            FROM itemTags it
            JOIN tags t ON it.tagID = t.tagID
            WHERE it.itemID = ?
        """, (item_id,))
        return [row["name"] for row in cursor.fetchall()]

    def _get_item_collections(self, item_id: int) -> List[str]:
        """获取文献所属的收藏夹"""
        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT c.collectionName
            FROM collectionItems ci
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE ci.itemID = ?
        """, (item_id,))
        return [row["collectionName"] for row in cursor.fetchall()]

    def _get_item_annotations(self, item_id: int) -> List[Dict]:
        """获取文献的标注"""
        if not self.include_annotations:
            return []

        conn = self._get_connection()
        annotations = []

        # 方式1: 直接查找以该 item 为父级的 PDF 附件的标注
        cursor = conn.execute("""
            SELECT ian.text, ian.comment, ian.color, ian.pageLabel
            FROM itemAnnotations ian
            WHERE ian.parentItemID IN (
                SELECT itemID FROM itemAttachments WHERE parentItemID = ?
            )
            AND ian.text IS NOT NULL AND ian.text != ''
        """, (item_id,))

        for row in cursor.fetchall():
            annotations.append({
                "text": row["text"],
                "comment": row["comment"] or "",
                "color": row["color"] or "",
                "page": row["pageLabel"] or "",
            })

        # 方式2: 如果该 item 本身就是 PDF，查找其直接标注
        cursor = conn.execute("""
            SELECT ian.text, ian.comment, ian.color, ian.pageLabel
            FROM itemAnnotations ian
            WHERE ian.parentItemID = ?
            AND ian.text IS NOT NULL AND ian.text != ''
        """, (item_id,))

        for row in cursor.fetchall():
            annotations.append({
                "text": row["text"],
                "comment": row["comment"] or "",
                "color": row["color"] or "",
                "page": row["pageLabel"] or "",
            })

        return annotations

    def _get_item_notes(self, item_id: int) -> List[str]:
        """获取文献的笔记"""
        if not self.include_notes:
            return []

        conn = self._get_connection()
        cursor = conn.execute("""
            SELECT n.note
            FROM itemNotes n
            WHERE n.itemID = ?
            AND n.note IS NOT NULL AND n.note != ''
        """, (item_id,))

        notes = []
        for row in cursor.fetchall():
            # 清理 HTML 标签
            note_text = re.sub(r'<[^>]+>', '', row["note"])
            note_text = note_text.strip()
            if note_text:
                notes.append(note_text)

        return notes

    def get_item(self, item_id: int) -> Optional[ZoteroItem]:
        """
        获取单个文献的详细信息

        Args:
            item_id: 文献 ID

        Returns:
            ZoteroItem 或 None
        """
        conn = self._get_connection()

        # 检查文献是否存在且未删除
        cursor = conn.execute("""
            SELECT * FROM items
            WHERE itemID = ?
            AND itemID NOT IN (SELECT itemID FROM deletedItems)
        """, (item_id,))
        row = cursor.fetchone()
        if not row:
            return None

        # 获取基本字段
        title = self._get_item_field(item_id, "title")
        if not title:
            return None

        # 获取 itemType
        cursor = conn.execute("SELECT typeName FROM itemTypes WHERE itemTypeID = ?", (row["itemTypeID"],))
        type_row = cursor.fetchone()
        item_type = type_row["typeName"] if type_row else "unknown"

        # 获取 PDF 文件路径
        file_path = self._get_pdf_path(item_id)

        item = ZoteroItem(
            item_id=item_id,
            key=row["key"],
            title=title,
            item_type=item_type,
            creators=self._get_item_creators(item_id),
            abstract=self._get_item_field(item_id, "abstractNote") or "",
            date=self._get_item_field(item_id, "date") or "",
            tags=self._get_item_tags(item_id),
            collections=self._get_item_collections(item_id),
            doi=self._get_item_field(item_id, "DOI") or "",
            url=self._get_item_field(item_id, "url") or "",
            publisher=self._get_item_field(item_id, "publisher") or "",
            publication_title=self._get_item_field(item_id, "publicationTitle") or "",
            journal_abbreviation=self._get_item_field(item_id, "journalAbbreviation") or "",
            volume=self._get_item_field(item_id, "volume") or "",
            issue=self._get_item_field(item_id, "issue") or "",
            pages=self._get_item_field(item_id, "pages") or "",
            file_path=file_path,
            annotations=self._get_item_annotations(item_id),
            notes=self._get_item_notes(item_id),
        )

        return item

    def _get_pdf_path(self, item_id: int) -> Optional[str]:
        """获取 PDF 文件路径"""
        conn = self._get_connection()
        
        # 查找附件
        cursor = conn.execute("""
            SELECT ia.path, ia.storageHash, ia.contentType
            FROM itemAttachments ia
            WHERE ia.parentItemID = ?
            AND ia.linkMode = 0
            LIMIT 1
        """, (item_id,))
        row = cursor.fetchone()
        
        if row:
            content_type = row["contentType"] or ""
            storage_hash = row["storageHash"]
            
            # 检查是否是 PDF 或其他可读格式
            if any(ext in content_type for ext in ['pdf', 'document', 'presentation']):
                # 方法1: 如果有 storageHash，用 hash 目录
                if storage_hash:
                    hash_dir = self.storage_dir / storage_hash
                    if hash_dir.exists():
                        # 找到实际文件
                        for f in hash_dir.iterdir():
                            if f.is_file():
                                return str(f)
                
                # 方法2: 从 path 中提取文件名
                path = row["path"]
                if path and path.startswith("storage:"):
                    filename = path.replace("storage:", "")
                    # 直接在 storage 根目录查找
                    full_path = self.storage_dir / filename
                    if full_path.exists():
                        return str(full_path)
                    
                    # 在子目录中查找
                    for item_dir in self.storage_dir.iterdir():
                        if item_dir.is_dir():
                            full_path = item_dir / filename
                            if full_path.exists():
                                return str(full_path)
        
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
            文献 ID 列表
        """
        conn = self._get_connection()

        def get_items_recursive(col_id: int) -> List[int]:
            cursor = conn.execute(
                "SELECT itemID FROM collectionItems WHERE collectionID = ?",
                (col_id,),
            )
            items = [row["itemID"] for row in cursor.fetchall()]

            if recursive:
                cursor = conn.execute(
                    "SELECT collectionID FROM collections WHERE parentCollectionID = ?",
                    (col_id,),
                )
                for child_row in cursor.fetchall():
                    items.extend(get_items_recursive(child_row["collectionID"]))

            return items

        return get_items_recursive(collection_id)

    def load_items(
        self,
        collection_id: Optional[int] = None,
        search_query: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[ZoteroItem]:
        """
        加载文献列表

        Args:
            collection_id: 收藏夹 ID
            search_query: 搜索关键词
            tag_filter: 标签过滤
            limit: 限制数量

        Returns:
            ZoteroItem 列表
        """
        items = []

        if collection_id:
            item_ids = self.get_items_in_collection(collection_id)
        else:
            conn = self._get_connection()
            cursor = conn.execute("""
                SELECT itemID FROM items
                WHERE itemID NOT IN (SELECT itemID FROM deletedItems)
                ORDER BY dateModified DESC
                LIMIT ?
            """, (limit * 2,))  # 获取更多以便过滤
            item_ids = [row["itemID"] for row in cursor.fetchall()]

        for item_id in item_ids[:limit * 2]:
            item = self.get_item(item_id)
            if not item:
                continue

            # 搜索过滤
            if search_query:
                query = search_query.lower()
                if query not in item.title.lower() and query not in item.abstract.lower():
                    continue

            # 标签过滤
            if tag_filter and tag_filter not in item.tags:
                continue

            items.append(item)
            if len(items) >= limit:
                break

        return items

    def load_as_documents(
        self,
        collection_id: Optional[int] = None,
        search_query: Optional[str] = None,
        tag_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[LlamaDocument]:
        """
        加载为 LlamaIndex Document

        Args:
            collection_id: 收藏夹 ID
            search_query: 搜索关键词
            tag_filter: 标签过滤
            limit: 限制数量

        Returns:
            Document 列表
        """
        items = self.load_items(
            collection_id=collection_id,
            search_query=search_query,
            tag_filter=tag_filter,
            limit=limit,
        )

        documents = []
        for item in items:
            text = item.to_text()
            doc = LlamaDocument(
                text=text,
                metadata={
                    "source": "zotero",
                    "item_id": item.item_id,
                    "key": item.key,
                    "title": item.title,
                    "item_type": item.item_type,
                    "creators": item.creators,
                    "date": item.date,
                    "tags": item.tags,
                    "collections": item.collections,
                    "doi": item.doi,
                    "file_path": item.file_path,
                    "annotation_count": len(item.annotations),
                    "note_count": len(item.notes),
                },
            )
            documents.append(doc)

        return documents

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        conn = self._get_connection()

        stats = {}

        # 总文献数
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM items
            WHERE itemID NOT IN (SELECT itemID FROM deletedItems)
        """)
        stats["total_items"] = cursor.fetchone()["cnt"]

        # 总标注数
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM itemAnnotations
            WHERE text IS NOT NULL AND text != ''
        """)
        stats["total_annotations"] = cursor.fetchone()["cnt"]

        # 总笔记数
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM itemNotes
            WHERE note IS NOT NULL AND note != ''
        """)
        stats["total_notes"] = cursor.fetchone()["cnt"]

        # 收藏夹数
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM collections")
        stats["total_collections"] = cursor.fetchone()["cnt"]

        # 按类型统计
        cursor = conn.execute("""
            SELECT it.typeName, COUNT(*) as cnt
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
            GROUP BY i.itemTypeID
            ORDER BY cnt DESC
            LIMIT 10
        """)
        stats["items_by_type"] = [
            {"type": row["typeName"], "count": row["cnt"]}
            for row in cursor.fetchall()
        ]

        return stats


class ZoteroClassifier:
    """
    Zotero 文献分类器

    根据收藏夹和标签对文献进行分类。
    """

    def __init__(self, reader: ZoteroReader):
        self.reader = reader
        self.collections = {c["id"]: c["name"] for c in reader.get_collections()}

    def classify(self, item: ZoteroItem) -> List[str]:
        """
        对文献进行分类

        Args:
            item: ZoteroItem

        Returns:
            匹配的知识库 ID 列表
        """
        matched = []

        # 按收藏夹分类
        for col_name in item.collections:
            col_id = self._find_collection_id(col_name)
            if col_id:
                matched.append(f"zotero_col_{col_id}")

        # 按标签分类
        for tag in item.tags:
            # 可以在这里添加标签到知识库的映射
            pass

        return list(set(matched))

    def _find_collection_id(self, name: str) -> Optional[int]:
        """根据名称查找收藏夹 ID"""
        for col_id, col_name in self.collections.items():
            if col_name == name:
                return col_id
        return None


def create_zotero_reader(
    data_dir: Optional[Path] = None,
    include_annotations: bool = True,
    include_notes: bool = True,
) -> ZoteroReader:
    """
    创建 Zotero 读取器

    Args:
        data_dir: Zotero 数据目录
        include_annotations: 是否包含标注
        include_notes: 是否包含笔记

    Returns:
        ZoteroReader 实例
    """
    return ZoteroReader(
        data_dir=data_dir,
        include_annotations=include_annotations,
        include_notes=include_notes,
    )
