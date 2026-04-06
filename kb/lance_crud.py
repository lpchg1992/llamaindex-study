"""
LanceDB CRUD 工具

提供完整的 LanceDB 增删改查功能，可被 API 和 CLI 调用。

功能：
- 列出所有知识库的 LanceDB 表
- 查看表统计信息（行数、大小、schema）
- 查询表中的原始数据
- 按 doc_id 或源文件删除记录
- 导出数据
- 去重分析
"""

import json
import lancedb
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional, List, Dict, Iterator

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LanceTableStats:
    """表统计信息"""

    kb_id: str
    table_name: str
    uri: str
    row_count: int
    size_bytes: int
    size_mb: float
    size_gb: float
    columns: List[str]
    schema_fields: List[Dict[str, Any]]


@dataclass
class LanceDocInfo:
    """文档信息（同一 doc_id 的节点聚合）"""

    doc_id: str
    node_count: int
    total_chars: int
    source_file: Optional[str]
    first_node_id: str
    last_node_id: str


@dataclass
class LanceNodeInfo:
    """节点信息"""

    id: str
    doc_id: str
    text: str
    text_length: int
    metadata: Dict[str, Any]


class LanceCRUDService:
    """LanceDB CRUD 服务"""

    # 默认 LanceDB 存储根目录
    DEFAULT_LANCE_ROOT = Path.home() / ".llamaindex" / "storage"

    @staticmethod
    def connect(kb_id: str) -> lancedb.LanceDBConnection:
        """连接到知识库的 LanceDB

        Args:
            kb_id: 知识库 ID

        Returns:
            LanceDB 连接
        """
        # 尝试从 registry 获取 persist_dir
        from kb.registry import registry

        kb = registry.get(kb_id)
        if kb:
            persist_dir = kb.persist_dir
        else:
            # 从数据库获取
            from kb.database import init_kb_meta_db

            kb_meta = init_kb_meta_db().get(kb_id)
            if kb_meta and kb_meta.get("persist_path"):
                persist_dir = Path(kb_meta["persist_path"])
            else:
                persist_dir = LanceCRUDService.DEFAULT_LANCE_ROOT / kb_id

        return lancedb.connect(str(persist_dir))

    @staticmethod
    def list_tables(kb_id: str) -> List[str]:
        """列出知识库的所有表

        Args:
            kb_id: 知识库 ID

        Returns:
            表名列表
        """
        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        return list(result.tables) if hasattr(result, "tables") else []

    @staticmethod
    def get_table_stats(
        kb_id: str, table_name: Optional[str] = None
    ) -> LanceTableStats:
        """获取表的统计信息

        Args:
            kb_id: 知识库 ID
            table_name: 表名（默认为 kb_id）

        Returns:
            表统计信息
        """
        if table_name is None:
            table_name = kb_id

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在于知识库 {kb_id}")

        table = db.open_table(table_name)
        count = table.count_rows()

        # 计算大小
        uri = str(db.uri)
        total_size = 0
        kb_path = Path(uri)
        if kb_path.exists():
            for f in kb_path.rglob("*"):
                if f.is_file() and not f.name.startswith("."):
                    total_size += f.stat().st_size

        # 获取 schema
        schema = table.schema
        columns = [f.name for f in schema]
        schema_fields = []
        for field in schema:
            schema_fields.append(
                {
                    "name": field.name,
                    "type": str(field.type),
                }
            )

        return LanceTableStats(
            kb_id=kb_id,
            table_name=table_name,
            uri=uri,
            row_count=count,
            size_bytes=total_size,
            size_mb=total_size / 1024 / 1024,
            size_gb=total_size / 1024 / 1024 / 1024,
            columns=columns,
            schema_fields=schema_fields,
        )

    @staticmethod
    def list_all_tables() -> List[Dict[str, Any]]:
        """列出所有知识库的表

        Returns:
            每个知识库的表信息列表
        """
        from kb.registry import registry
        from kb.database import init_kb_meta_db

        results = []

        # 从 registry 获取
        for kb in registry.list_all():
            try:
                stats = LanceCRUDService.get_table_stats(kb.id)
                results.append(
                    {
                        "kb_id": kb.id,
                        "name": kb.name,
                        "table_name": stats.table_name,
                        "uri": stats.uri,
                        "row_count": stats.row_count,
                        "size_mb": stats.size_mb,
                        "status": "ok",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "kb_id": kb.id,
                        "name": kb.name,
                        "status": "error",
                        "error": str(e),
                    }
                )

        # 从数据库获取（不在 registry 中的）
        kb_meta_db = init_kb_meta_db()
        for row in kb_meta_db.get_all():
            kb_id = row.get("kb_id")
            if any(r["kb_id"] == kb_id for r in results):
                continue
            try:
                stats = LanceCRUDService.get_table_stats(kb_id)
                results.append(
                    {
                        "kb_id": kb_id,
                        "name": row.get("name", kb_id),
                        "table_name": stats.table_name,
                        "uri": stats.uri,
                        "row_count": stats.row_count,
                        "size_mb": stats.size_mb,
                        "status": "ok",
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "kb_id": kb_id,
                        "name": row.get("name", kb_id),
                        "status": "error",
                        "error": str(e),
                    }
                )

        return results

    @staticmethod
    def query_nodes(
        kb_id: str,
        table_name: Optional[str] = None,
        doc_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        text_contains: Optional[str] = None,
    ) -> List[LanceNodeInfo]:
        """查询节点

        Args:
            kb_id: 知识库 ID
            table_name: 表名
            doc_id: 按 doc_id 过滤
            limit: 返回数量
            offset: 偏移
            text_contains: 文本包含的关键词

        Returns:
            节点列表
        """
        if table_name is None:
            table_name = kb_id

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)

        # 构建查询
        if doc_id:
            query = table.query().where(f"doc_id = '{doc_id}'")
        else:
            query = table.query()

        if text_contains:
            # LanceDB 支持 full-text search
            query = query.search(text_contains, query_type="fts")

        query = query.offset(offset).limit(limit)
        df = query.to_pandas()

        results = []
        for _, row in df.iterrows():
            text = str(row.get("text", ""))
            metadata = row.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}

            results.append(
                LanceNodeInfo(
                    id=str(row.get("id", "")),
                    doc_id=str(row.get("doc_id", "")),
                    text=text,
                    text_length=len(text),
                    metadata=metadata,
                )
            )

        return results

    @staticmethod
    def iter_nodes(
        kb_id: str,
        table_name: Optional[str] = None,
        batch_size: int = 1000,
    ) -> Iterator[LanceNodeInfo]:
        """迭代所有节点（用于大数据量）

        Args:
            kb_id: 知识库 ID
            table_name: 表名
            batch_size: 批大小

        Yields:
            节点信息
        """
        if table_name is None:
            table_name = kb_id

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)
        total = table.count_rows()

        for offset in range(0, total, batch_size):
            df = table.query().offset(offset).limit(batch_size).to_pandas()

            for _, row in df.iterrows():
                text = str(row.get("text", ""))
                metadata = row.get("metadata", {})
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}

                yield LanceNodeInfo(
                    id=str(row.get("id", "")),
                    doc_id=str(row.get("doc_id", "")),
                    text=text,
                    text_length=len(text),
                    metadata=metadata,
                )

    @staticmethod
    def get_doc_ids(
        kb_id: str,
        table_name: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[str]:
        """获取所有唯一的 doc_id

        Args:
            kb_id: 知识库 ID
            table_name: 表名
            limit: 限制数量

        Returns:
            doc_id 列表
        """
        if table_name is None:
            table_name = kb_id

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)

        # 使用 distinct 获取唯一的 doc_id
        df = table.query().select("doc_id").to_pandas()
        doc_ids = df["doc_id"].unique().tolist()

        if limit:
            doc_ids = doc_ids[:limit]

        return doc_ids

    @staticmethod
    def get_doc_summary(
        kb_id: str,
        table_name: Optional[str] = None,
    ) -> List[LanceDocInfo]:
        """获取文档摘要（按 doc_id 聚合）

        Args:
            kb_id: 知识库 ID
            table_name: 表名

        Returns:
            文档信息列表
        """
        if table_name is None:
            table_name = kb_id

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)
        df = table.to_pandas()

        # 按 doc_id 分组
        grouped = df.groupby("doc_id")

        results = []
        for doc_id, group in grouped:
            texts = group["text"].astype(str)
            total_chars = texts.str.len().sum()

            # 尝试从 metadata 提取 source_file
            source_file = None
            for _, row in group.iterrows():
                try:
                    meta = row.get("metadata", {})
                    if isinstance(meta, str):
                        meta = json.loads(meta)
                    if isinstance(meta, dict) and "_node_content" in meta:
                        nc = json.loads(meta["_node_content"])
                        rels = nc.get("relationships", {})
                        if "1" in rels:
                            source_file = rels["1"].get("metadata", {}).get("file_path")
                            if source_file:
                                source_file = Path(source_file).name
                                break
                except:
                    pass

            node_ids = group["id"].tolist()

            results.append(
                LanceDocInfo(
                    doc_id=doc_id,
                    node_count=len(group),
                    total_chars=int(total_chars),
                    source_file=source_file,
                    first_node_id=node_ids[0] if node_ids else "",
                    last_node_id=node_ids[-1] if node_ids else "",
                )
            )

        # 按 node_count 降序排序
        results.sort(key=lambda x: x.node_count, reverse=True)

        return results

    @staticmethod
    def delete_by_doc_ids(
        kb_id: str,
        doc_ids: List[str],
        table_name: Optional[str] = None,
    ) -> int:
        """按 doc_id 删除节点

        Args:
            kb_id: 知识库 ID
            doc_ids: 要删除的 doc_id 列表
            table_name: 表名

        Returns:
            删除的节点数
        """
        if table_name is None:
            table_name = kb_id

        if not doc_ids:
            return 0

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)

        # 构建删除条件
        doc_ids_str = " OR ".join([f"doc_id = '{did}'" for did in doc_ids])

        # 执行删除
        result = table.delete(f"{doc_ids_str}")
        return getattr(result, "num_deleted", 0)

    @staticmethod
    def delete_by_source_file(
        kb_id: str,
        source_file: str,
        table_name: Optional[str] = None,
    ) -> int:
        """按源文件路径删除节点

        Args:
            kb_id: 知识库 ID
            source_file: 源文件路径（会进行模糊匹配）
            table_name: 表名

        Returns:
            删除的节点数
        """
        if table_name is None:
            table_name = kb_id

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)

        # 通过 metadata 中的 source 字段匹配
        escaped = source_file.replace("'", "''")
        result = table.delete(f"metadata:source LIKE '%{escaped}%'")

        return getattr(result, "num_deleted", 0)

    @staticmethod
    def delete_by_node_ids(
        kb_id: str,
        node_ids: List[str],
        table_name: Optional[str] = None,
    ) -> int:
        """按节点 ID 删除

        Args:
            kb_id: 知识库 ID
            node_ids: 要删除的节点 ID 列表
            table_name: 表名

        Returns:
            删除的节点数
        """
        if table_name is None:
            table_name = kb_id

        if not node_ids:
            return 0

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if table_name not in table_names:
            raise ValueError(f"表 {table_name} 不存在")

        table = db.open_table(table_name)

        deleted = 0
        for node_id in node_ids:
            try:
                result = table.delete(f"id = '{node_id}'")
                deleted += getattr(result, "num_deleted", 0)
            except Exception as e:
                logger.warning(f"删除节点 {node_id} 失败: {e}")

        return deleted

    @staticmethod
    def find_duplicate_sources(
        kb_id: str,
        table_name: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """查找重复的源文件（同一路径有多个 doc_id）

        Args:
            kb_id: 知识库 ID
            table_name: 表名

        Returns:
            {源文件路径: [doc_id, ...], ...}
        """
        docs = LanceCRUDService.get_doc_summary(kb_id, table_name)

        # 按 source_file 分组
        source_to_docs: Dict[str, List[str]] = {}
        for doc in docs:
            if doc.source_file:
                if doc.source_file not in source_to_docs:
                    source_to_docs[doc.source_file] = []
                source_to_docs[doc.source_file].append(doc.doc_id)

        # 只返回有多个 doc_id 的
        return {k: v for k, v in source_to_docs.items() if len(v) > 1}

    @staticmethod
    def export_to_jsonl(
        kb_id: str,
        output_path: str,
        table_name: Optional[str] = None,
    ) -> int:
        """导出数据到 JSONL 文件

        Args:
            kb_id: 知识库 ID
            output_path: 输出文件路径
            table_name: 表名

        Returns:
            导出的记录数
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        count = 0
        with open(output, "w", encoding="utf-8") as f:
            for node in LanceCRUDService.iter_nodes(kb_id, table_name):
                record = {
                    "id": node.id,
                    "doc_id": node.doc_id,
                    "text": node.text,
                    "text_length": node.text_length,
                    "metadata": node.metadata,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        return count

    @staticmethod
    def rebuild_docstore(kb_id: str) -> int:
        """重建 docstore（从 LanceDB 节点数据）

        Args:
            kb_id: 知识库 ID

        Returns:
            重建的节点数
        """
        from llama_index.core.storage.docstore import SimpleDocumentStore
        from llama_index.core.schema import TextNode, Document

        db = LanceCRUDService.connect(kb_id)
        table = db.open_table(kb_id)
        total = table.count_rows()

        docstore = SimpleDocumentStore()
        nodes_rebuilt = 0

        for offset in range(0, total, 5000):
            batch = table.query().offset(offset).limit(5000).to_pandas()

            batch_nodes = []
            for _, row in batch.iterrows():
                try:
                    metadata = row.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}

                    node_content_str = metadata.get("_node_content", "")
                    if not node_content_str:
                        continue

                    node_data = json.loads(node_content_str)
                    node_type = metadata.get("_node_type", "")

                    if node_type == "TextNode":
                        node = TextNode(
                            id_=node_data.get("id_") or row.get("id"),
                            text=node_data.get("text", ""),
                            metadata=node_data.get("metadata", {}),
                            relationships=node_data.get("relationships", {}),
                        )
                    else:
                        node = Document(
                            id_=node_data.get("id_") or row.get("id"),
                            text=node_data.get("text", ""),
                            metadata=node_data.get("metadata", {}),
                            relationships=node_data.get("relationships", {}),
                        )

                    batch_nodes.append(node)
                    nodes_rebuilt += 1
                except Exception as e:
                    logger.debug(f"处理节点失败: {e}")
                    continue

            if batch_nodes:
                docstore.add_documents(batch_nodes)

        # 保存
        persist_path = Path(db.uri) / "docstore.json"
        docstore.persist(persist_path=str(persist_path))

        logger.info(f"docstore 已重建: {nodes_rebuilt} 节点, 保存到 {persist_path}")
        return nodes_rebuilt

    @staticmethod
    def get_schema(kb_id: str, table_name: Optional[str] = None) -> Dict[str, Any]:
        """获取表结构

        Args:
            kb_id: 知识库 ID
            table_name: 表名

        Returns:
            schema 信息
        """
        if table_name is None:
            table_name = kb_id

        stats = LanceCRUDService.get_table_stats(kb_id, table_name)
        return {
            "kb_id": stats.kb_id,
            "table_name": stats.table_name,
            "uri": stats.uri,
            "row_count": stats.row_count,
            "columns": stats.columns,
            "fields": stats.schema_fields,
        }
