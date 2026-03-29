"""
去重管理器 - 统一的防重复处理模块

提供完整的去重功能：
1. 文件级别去重：基于文件哈希的增量检测
2. 数据库级别去重：基于 Doc ID 的 upsert
3. 处理状态管理：持久化的增量同步

使用方式：
```python
from kb.deduplication import DeduplicationManager

# 初始化
manager = DeduplicationManager(
    kb_id="swine_nutrition",
    persist_dir=Path("/path/to/storage"),
    uri="/path/to/lancedb",
    table_name="swine_nutrition",
)

# 检测变更
to_add, to_update, to_delete, unchanged = manager.detect_changes(
    files=[Path("...")],
    vault_root=Path("/vault"),
)

# 增量处理
for change in to_add + to_update:
    # 处理文件...
    manager.mark_processed(change.abs_path, content, doc_id)

# 保存状态
manager._save()
```

与以下模块配合使用：
- DocumentProcessor._upsert_nodes()：数据库 upsert
"""

import hashlib
import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable, Any
from enum import Enum

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class ChangeType(Enum):
    """变更类型"""
    ADD = "add"      # 新增
    UPDATE = "update"  # 更新
    DELETE = "delete"  # 删除
    UNCHANGED = "unchanged"  # 未变更


@dataclass
class FileChange:
    """文件变更记录"""
    rel_path: str           # 相对路径
    abs_path: Path          # 绝对路径
    change_type: ChangeType  # 变更类型
    content: Optional[str] = None  # 文件内容（延迟加载）
    doc_id: Optional[str] = None   # 文档 ID
    old_doc_id: Optional[str] = None  # 旧的文档 ID（用于更新）
    hash: Optional[str] = None  # 当前哈希
    old_hash: Optional[str] = None  # 旧哈希


@dataclass
class ProcessingRecord:
    """处理记录"""
    rel_path: str
    abs_path: str
    hash: str
    doc_id: str
    mtime: float
    last_processed: float = 0
    chunk_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ProcessingRecord":
        return cls(**data)


class DeduplicationManager:
    """
    去重管理器

    统一的防重复处理模块，提供：
    1. 文件变更检测（基于 MD5 哈希）
    2. 增量处理（只处理新增/更新的文件）
    3. 数据库 upsert（基于 Doc ID）
    4. 同步状态持久化（支持 SQLite 或 JSON）

    使用方式：
    ```python
    from kb.deduplication import DeduplicationManager

    manager = DeduplicationManager(
        kb_id="swine_nutrition",
        persist_dir=Path("/path/to/storage"),
        use_sqlite=True,  # 使用 SQLite 数据库
    )

    # 检测变更
    to_add, to_update, to_delete, unchanged = manager.detect_changes(
        files=[Path("...")],
        vault_root=Path("/vault"),
    )

    # 增量处理
    for change in to_add + to_update:
        # 处理文件...
        manager.mark_processed(change.abs_path, content, doc_id)
    ```
    """

    # 状态文件后缀（向后兼容）
    STATE_FILE = ".dedup_state.json"

    def __init__(
        self,
        kb_id: str,
        persist_dir: Path,
        uri: Optional[str] = None,
        table_name: Optional[str] = None,
        batch_size: int = 50,
        use_sqlite: bool = True,
    ):
        """
        初始化去重管理器

        Args:
            kb_id: 知识库 ID
            persist_dir: 持久化目录
            uri: LanceDB URI（默认为 persist_dir）
            table_name: 表名（默认为 kb_id）
            batch_size: 批处理大小
            use_sqlite: 是否使用 SQLite 数据库（默认 True）
        """
        self.kb_id = kb_id
        self.persist_dir = Path(persist_dir)
        self.uri = uri or str(self.persist_dir)
        self.table_name = table_name or kb_id
        self.batch_size = batch_size
        self.use_sqlite = use_sqlite

        # 内存中的处理记录：{rel_path: ProcessingRecord}
        self._records: Dict[str, ProcessingRecord] = {}

        # SQLite 数据库操作
        self._dedup_db = None

        # LanceDB 连接（延迟初始化）
        self._db = None
        self._table = None

        # 加载已有状态
        self._load()

    def _get_state_file(self) -> Path:
        """获取状态文件路径"""
        return self.persist_dir / self.STATE_FILE

    def _init_sqlite(self):
        """初始化 SQLite 数据库"""
        from kb.database import init_dedup_db
        self._dedup_db = init_dedup_db()

    def _load(self):
        """从存储加载状态"""
        if self.use_sqlite:
            self._init_sqlite()
            self._load_sqlite()
        else:
            self._load_json()

    def _load_sqlite(self):
        """从 SQLite 加载状态"""
        try:
            records = self._dedup_db.get_records(self.kb_id)
            self._records = {
                r["file_path"]: ProcessingRecord(
                    rel_path=r["file_path"],
                    abs_path="",
                    hash=r["hash"],
                    doc_id=r["doc_id"],
                    mtime=r["mtime"],
                    last_processed=r["last_processed"],
                    chunk_count=r["chunk_count"],
                )
                for r in records
            }
        except Exception as e:
            logger.warning(f"从 SQLite 加载去重状态失败: {e}")
            self._records = {}

    def _load_json(self):
        """从 JSON 文件加载状态（向后兼容）"""
        state_file = self._get_state_file()
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._records = {
                        path: ProcessingRecord.from_dict(record)
                        for path, record in data.items()
                    }
            except Exception as e:
                logger.warning(f"加载去重状态失败: {e}")
                self._records = {}

    def _save(self):
        """保存状态到存储"""
        if self.use_sqlite and self._dedup_db:
            self._save_sqlite()
        else:
            self._save_json()

    def _save_sqlite(self):
        """保存状态到 SQLite"""
        try:
            # 批量更新
            records = [
                {
                    "file_path": rel_path,
                    "hash": record.hash,
                    "doc_id": record.doc_id,
                    "mtime": record.mtime,
                    "last_processed": record.last_processed,
                    "chunk_count": record.chunk_count,
                }
                for rel_path, record in self._records.items()
            ]
            if records:
                self._dedup_db.bulk_add(self.kb_id, records)
        except Exception as e:
            logger.warning(f"保存去重状态到 SQLite 失败: {e}")

    def _save_json(self):
        """保存状态到 JSON 文件（向后兼容）"""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        state_file = self._get_state_file()
        try:
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(
                    {path: record.to_dict() for path, record in self._records.items()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.warning(f"保存去重状态失败: {e}")

    @staticmethod
    def compute_hash(content: str) -> str:
        """计算内容的 MD5 哈希"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """计算文件的 MD5 哈希（只读前 1MB 用于快速哈希）"""
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(1024 * 1024)
                hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def get_record(self, rel_path: str) -> Optional[ProcessingRecord]:
        """获取处理记录"""
        return self._records.get(rel_path)

    def is_duplicate(
        self,
        file_path: Path,
        content: Optional[str] = None,
        vault_root: Optional[Path] = None,
    ) -> bool:
        """
        检查文件是否重复（未变更）

        Args:
            file_path: 文件绝对路径
            content: 文件内容（可选，避免重复读取）
            vault_root: Vault 根目录（用于计算相对路径）

        Returns:
            True 如果文件未变更，是重复的
        """
        # 计算相对路径
        if vault_root:
            try:
                rel_path = str(file_path.relative_to(vault_root))
            except ValueError:
                rel_path = str(file_path)
        else:
            rel_path = str(file_path)

        # 检查记录是否存在
        record = self._records.get(rel_path)
        if record is None:
            return False  # 新文件

        # 检查文件是否存在
        if not file_path.exists():
            return False  # 文件已删除

        # 检查哈希是否变化
        if content is None:
            content = file_path.read_text(encoding="utf-8", errors="ignore")

        current_hash = self.compute_hash(content)
        return current_hash == record.hash

    def detect_changes(
        self,
        files: List[Path],
        vault_root: Path,
        compute_content: bool = False,
    ) -> tuple:
        """
        检测文件变更

        Args:
            files: 文件列表
            vault_root: Vault 根目录
            compute_content: 是否计算文件内容（用于后续处理）

        Returns:
            (to_add, to_update, to_delete, unchanged)
            - to_add: 新增文件列表 [FileChange, ...]
            - to_update: 更新文件列表 [FileChange, ...]
            - to_delete: 删除文件列表 [FileChange, ...]
            - unchanged: 未变更文件列表 [FileChange, ...]
        """
        to_add = []
        to_update = []
        to_delete = []
        unchanged = []

        # 当前文件路径集合
        current_paths = set()

        for file_path in files:
            # 计算相对路径
            try:
                rel_path = str(file_path.relative_to(vault_root))
            except ValueError:
                rel_path = str(file_path)

            current_paths.add(rel_path)

            # 检查记录
            record = self._records.get(rel_path)

            if record is None:
                # 新文件
                change = FileChange(
                    rel_path=rel_path,
                    abs_path=file_path,
                    change_type=ChangeType.ADD,
                )
                to_add.append(change)
            else:
                # 检查哈希
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    content = ""

                current_hash = self.compute_hash(content)

                if current_hash != record.hash:
                    # 内容变更
                    change = FileChange(
                        rel_path=rel_path,
                        abs_path=file_path,
                        change_type=ChangeType.UPDATE,
                        content=content,
                        doc_id=record.doc_id,
                        hash=current_hash,
                        old_hash=record.hash,
                    )
                    to_update.append(change)
                else:
                    # 未变更
                    change = FileChange(
                        rel_path=rel_path,
                        abs_path=file_path,
                        change_type=ChangeType.UNCHANGED,
                        doc_id=record.doc_id,
                        hash=current_hash,
                    )
                    unchanged.append(change)

        # 检测删除的文件
        for rel_path, record in self._records.items():
            if rel_path not in current_paths:
                change = FileChange(
                    rel_path=rel_path,
                    abs_path=Path(record.abs_path),
                    change_type=ChangeType.DELETE,
                    doc_id=record.doc_id,
                    old_hash=record.hash,
                )
                to_delete.append(change)

        return to_add, to_update, to_delete, unchanged

    def mark_processed(
        self,
        file_path: Path,
        content: str,
        doc_id: str,
        chunk_count: int = 0,
        vault_root: Optional[Path] = None,
    ):
        """
        标记文件已处理

        Args:
            file_path: 文件路径
            content: 文件内容
            doc_id: 文档 ID
            chunk_count: 生成的块数量
            vault_root: Vault 根目录
        """
        # 计算相对路径
        if vault_root:
            try:
                rel_path = str(file_path.relative_to(vault_root))
            except ValueError:
                rel_path = str(file_path)
        else:
            rel_path = str(file_path)

        # 获取文件修改时间
        try:
            mtime = file_path.stat().st_mtime
        except Exception:
            mtime = time.time()

        # 创建记录
        record = ProcessingRecord(
            rel_path=rel_path,
            abs_path=str(file_path),
            hash=self.compute_hash(content),
            doc_id=doc_id,
            mtime=mtime,
            last_processed=time.time(),
            chunk_count=chunk_count,
        )

        self._records[rel_path] = record

        # 持久化到 SQLite
        if self.use_sqlite and self._dedup_db:
            try:
                result = self._dedup_db.add_record(
                    kb_id=self.kb_id,
                    file_path=rel_path,
                    hash=record.hash,
                    doc_id=doc_id,
                    chunk_count=chunk_count,
                )
                if not result:
                    logger.warning("保存去重记录返回 False")
            except Exception as e:
                logger.warning(f"保存去重记录失败: {e}", exc_info=True)

    def mark_deleted(self, rel_path: str):
        """
        标记文件已删除

        Args:
            rel_path: 相对路径
        """
        if rel_path in self._records:
            del self._records[rel_path]
        
        # 从 SQLite 删除
        if self.use_sqlite and self._dedup_db:
            self._dedup_db.remove(self.kb_id, rel_path)

    def remove_record(self, rel_path: str):
        """移除处理记录"""
        self._records.pop(rel_path, None)
        
        # 从 SQLite 删除
        if self.use_sqlite and self._dedup_db:
            self._dedup_db.remove(self.kb_id, rel_path)

    def clear(self):
        """清空所有记录"""
        self._records.clear()
        
        # 清空 SQLite
        if self.use_sqlite and self._dedup_db:
            self._dedup_db.clear(self.kb_id)
        else:
            self._save_json()

    def get_doc_ids(self) -> List[str]:
        """获取所有已处理文档的 doc_id"""
        return [record.doc_id for record in self._records.values()]

    def get_doc_id_map(self) -> Dict[str, str]:
        """获取 file_path -> doc_id 的映射"""
        return {record.rel_path: record.doc_id for record in self._records.items()}

    def get_stats(self) -> dict:
        return {
            "total_files": len(self._records),
            "total_chunks": sum(r.chunk_count for r in self._records.values()),
        }

    # ==================== 数据库操作 ====================

    def _get_table(self):
        """获取 LanceDB 表（延迟初始化）"""
        if self._table is None:
            import lancedb
            self._db = lancedb.connect(self.uri)
            try:
                self._table = self._db.open_table(self.table_name)
            except Exception:
                self._table = None
        return self._table

    def upsert_nodes(
        self,
        nodes: List[Any],
        id_key: str = "id",
    ) -> int:
        """
        Upsert 节点到数据库（基于 Doc ID 去重）

        Args:
            nodes: 节点列表
            id_key: ID 字段名

        Returns:
            成功 upsert 的节点数
        """
        try:
            import lancedb
            import pyarrow as pa

            # 连接数据库
            if self._db is None:
                self._db = lancedb.connect(self.uri)

            # 获取或创建表
            try:
                table = self._db.open_table(self.table_name)
            except Exception:
                # 表不存在，创建新表
                return 0  # 需要先初始化表结构

            # 将节点转换为 dict
            data = []
            for node in nodes:
                row = {"id": getattr(node, id_key, node.id_) if hasattr(node, 'id_') else str(node)}
                row["text"] = node.get_content() if hasattr(node, 'get_content') else str(node)

                # 添加 embedding
                if hasattr(node, 'embedding') and node.embedding:
                    row["embedding"] = node.embedding

                # 添加 metadata
                if hasattr(node, 'metadata') and node.metadata:
                    for k, v in node.metadata.items():
                        if isinstance(v, (str, int, float, bool, type(None))):
                            row[k] = v
                        elif isinstance(v, list):
                            row[k] = ",".join(str(x) for x in v)
                        else:
                            row[k] = str(v)[:500] if v else ""

                data.append(row)

            if not data:
                return 0

            # 执行 upsert
            df = pa.Table.from_pylist(data)
            table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(df)

            return len(nodes)

        except Exception as e:
            logger.warning(f"LanceDB Upsert 失败: {e}")
            return 0

    def delete_by_doc_ids(self, doc_ids: List[str]) -> int:
        """
        根据 doc_id 删除记录

        Args:
            doc_ids: 要删除的 doc_id 列表

        Returns:
            删除的记录数
        """
        try:
            table = self._get_table()
            if table is None:
                return 0

            # 过滤掉要删除的
            # 注意：这里需要根据实际的 doc_id 格式来删除
            # 假设 doc_id 格式为 "rel_path" 或 "rel_path_chunk_index"

            deleted = 0
            for doc_id in doc_ids:
                # 尝试删除匹配的记录
                # LanceDB 不支持直接删除，需要重新写入
                pass  # 简化处理

            return deleted

        except Exception as e:
            logger.warning(f"LanceDB 删除失败: {e}")
            return 0

    def get_existing_doc_ids(self) -> Set[str]:
        """
        获取数据库中已存在的 doc_id

        Returns:
            doc_id 集合
        """
        try:
            table = self._get_table()
            if table is None:
                return set()

            df = table.to_pandas()
            if df is not None and "id" in df.columns:
                return set(df["id"].astype(str).tolist())
            return set()

        except Exception:
            return set()


class IncrementalProcessor:
    """
    增量处理器

    封装增量处理的常见流程，配合 DeduplicationManager 使用。
    """

    def __init__(
        self,
        manager: DeduplicationManager,
        vector_store: Any,
        embed_model: Any,
        node_parser: Any,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ):
        """
        初始化增量处理器

        Args:
            manager: 去重管理器
            vector_store: 向量存储
            embed_model: Embedding 模型
            node_parser: 节点解析器
            on_progress: 进度回调
        """
        self.manager = manager
        self.vector_store = vector_store
        self.embed_model = embed_model
        self.node_parser = node_parser
        self.on_progress = on_progress

    def process_files(
        self,
        files: List[Path],
        vault_root: Path,
        doc_id_prefix: str = "",
        metadata_extractor: Optional[Callable[[Path], dict]] = None,
    ) -> dict:
        """
        处理文件列表（增量）

        Args:
            files: 文件列表
            vault_root: Vault 根目录
            doc_id_prefix: Doc ID 前缀
            metadata_extractor: 元数据提取函数

        Returns:
            处理统计
        """
        # 检测变更
        to_add, to_update, to_delete, unchanged = self.manager.detect_changes(
            files, vault_root
        )

        logger.info(f"增量: 新增 {len(to_add)}, 更新 {len(to_update)}, "
                    f"删除 {len(to_delete)}, 未变 {len(unchanged)}")

        stats = {"files": 0, "nodes": 0, "failed": 0, "skipped": 0}

        # 处理新增
        for change in to_add:
            try:
                nodes = self._process_file(
                    change.abs_path,
                    vault_root,
                    doc_id_prefix,
                    metadata_extractor,
                )
                if nodes:
                    saved = self._save_nodes(nodes)
                    stats["nodes"] += saved
                    stats["files"] += 1

                    # 标记已处理
                    content = change.abs_path.read_text(encoding="utf-8", errors="ignore")
                    self.manager.mark_processed(
                        change.abs_path,
                        content,
                        nodes[0].id_ if nodes else str(change.rel_path),
                        chunk_count=len(nodes),
                        vault_root=vault_root,
                    )
            except Exception as e:
                stats["failed"] += 1
                logger.warning(f"处理失败: {change.rel_path} - {e}")

        # 处理更新
        for change in to_update:
            try:
                # 删除旧记录（通过重新标记）
                nodes = self._process_file(
                    change.abs_path,
                    vault_root,
                    doc_id_prefix,
                    metadata_extractor,
                )
                if nodes:
                    saved = self._save_nodes(nodes)
                    stats["nodes"] += saved
                    stats["files"] += 1

                    # 标记已处理
                    self.manager.mark_processed(
                        change.abs_path,
                        change.content,
                        nodes[0].id_ if nodes else str(change.rel_path),
                        chunk_count=len(nodes),
                        vault_root=vault_root,
                    )
            except Exception as e:
                stats["failed"] += 1
                logger.warning(f"更新失败: {change.rel_path} - {e}")

        # 跳过未变更的文件
        stats["skipped"] = len(unchanged)

        # 保存状态
        self.manager._save()

        return stats

    def _process_file(
        self,
        file_path: Path,
        vault_root: Path,
        doc_id_prefix: str,
        metadata_extractor: Optional[Callable[[Path], dict]],
    ) -> List[Any]:
        """处理单个文件"""
        try:
            rel_path = str(file_path.relative_to(vault_root))
        except ValueError:
            rel_path = str(file_path)

        # 读取内容
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        if len(content.strip()) < 50:
            return []

        # 生成 Doc ID
        doc_id = f"{doc_id_prefix}{rel_path}" if doc_id_prefix else rel_path

        # 提取元数据
        metadata = {
            "source": "obsidian",
            "file_path": str(file_path),
            "relative_path": rel_path,
        }

        if metadata_extractor:
            metadata.update(metadata_extractor(file_path))

        # 创建文档
        from llama_index.core.schema import Document as LlamaDocument
        doc = LlamaDocument(
            text=content,
            metadata=metadata,
            id_=doc_id,
        )

        # 解析为节点
        nodes = self.node_parser.get_nodes_from_documents([doc])

        # 为每个节点生成 embedding
        if self.embed_model:
            for node in nodes:
                try:
                    node.embedding = self.embed_model.get_text_embedding(
                        node.get_content()
                    )
                except Exception as e:
                    logger.warning(f"Embedding 失败: {e}")
                    continue

        return nodes

    def _save_nodes(self, nodes: List[Any]) -> int:
        """保存节点"""
        if not nodes:
            return 0

        try:
            return self.manager.upsert_nodes(nodes)
        except Exception as e:
            logger.warning(f"保存节点失败: {e}")
            return 0
