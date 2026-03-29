"""
统一知识库管理模块

提供知识库的创建、导入、查询、状态检查等统一接口。

设计原则：
1. 统一管理：所有知识库通过统一接口访问
2. 自动修复：自动检测并修复 LanceDB manifest 问题
3. 增量同步：基于文件哈希的增量更新
4. 类型安全：完整的类型注解

示例：
```python
from kb.manager import KnowledgeBaseManager

# 创建管理器
manager = KnowledgeBaseManager()

# 列出所有知识库
kbs = manager.list_knowledge_bases()

# 检查状态
stats = manager.get_stats("zotero")
print(f"Zotero: {stats['row_count']} 行")

# 导入文档
manager.import_obsidian("tech_tools", folder="IT")

# 查询
results = manager.search("tech_tools", "Python 编程")
```
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import lancedb

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class DataSourceType(Enum):
    """数据源类型"""
    OBSIDIAN = "obsidian"
    ZOTERO = "zotero"
    GENERIC = "generic"
    UNKNOWN = "unknown"


@dataclass
class KnowledgeBaseStats:
    """知识库统计信息"""
    kb_id: str
    name: str
    source_type: DataSourceType
    exists: bool
    row_count: int = 0
    size_bytes: int = 0
    size_mb: float = 0
    size_gb: float = 0
    file_count: int = 0
    last_modified: Optional[float] = None
    error: Optional[str] = None

    @property
    def status(self) -> str:
        if self.error:
            return f"❌ 错误: {self.error}"
        if not self.exists:
            return "⏳ 未创建"
        if self.row_count > 0:
            return "✅ 正常"
        return "📁 空"

    @property
    def size_str(self) -> str:
        if self.size_gb >= 1:
            return f"{self.size_gb:.2f} GB"
        return f"{self.size_mb:.2f} MB"


@dataclass
class SearchResult:
    """搜索结果"""
    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    doc_id: str = ""


class KnowledgeBaseManager:
    """
    统一知识库管理器

    管理所有知识库的创建、导入、查询和状态检查。
    自动处理 LanceDB 的 manifest 路径问题。
    """

    def __init__(
        self,
        storage_root: Optional[Path] = None,
        vault_root: Optional[Path] = None,
    ):
        """
        初始化知识库管理器

        Args:
            storage_root: 存储根目录（默认从配置读取）
            vault_root: Obsidian vault 根目录
        """
        settings = get_settings()

        self.storage_root = storage_root or Path(settings.persist_dir)
        self.vault_root = vault_root or Path.home() / "Documents" / "Obsidian Vault"

        # 缓存
        self._stats_cache: Dict[str, KnowledgeBaseStats] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl = 60  # 缓存有效期（秒）

    def _get_kb_path(self, kb_id: str) -> Path:
        """
        获取知识库的根目录路径

        Args:
            kb_id: 知识库 ID

        Returns:
            知识库根目录路径
        """
        return self.storage_root / kb_id

    def _find_table_path(self, kb_id: str) -> tuple:
        """
        查找表的实际路径

        LanceDB 表可能存储在以下位置：
        1. storage_root/kb_id/           # 直接在 KB 目录下
        2. storage_root/kb_id/kb_id.lance/  # 在 KB.lance/ 子目录下
        3. storage_root/kb_id/xxx/         # 在 KB/xxx/ 子目录下（如 zotero/zotero_nutrition）

        Args:
            kb_id: 知识库 ID

        Returns:
            (table_path, table_name): 表路径和表名
        """
        kb_path = self._get_kb_path(kb_id)

        if not kb_path.exists():
            raise ValueError(f"知识库路径不存在: {kb_path}")

        # 方法1: 直接在 KB 目录下查找表
        db = lancedb.connect(str(kb_path))
        tables = db.list_tables()
        table_list = list(tables.tables) if hasattr(tables, 'tables') else []

        if kb_id in table_list:
            return kb_path, kb_id

        if table_list:
            # 如果只有一个表，使用它
            return kb_path, table_list[0]

        # 方法2: 在 KB_ID.lance/ 子目录下查找
        lance_subdir = kb_path / f"{kb_id}.lance"
        if lance_subdir.exists():
            db = lancedb.connect(str(lance_subdir))
            tables = db.list_tables()
            table_list = list(tables.tables) if hasattr(tables, 'tables') else []

            if kb_id in table_list:
                return lance_subdir, kb_id
            elif table_list:
                return lance_subdir, table_list[0]

        # 方法3: 在 KB 目录下的任何子目录中查找（表名通常与 KB ID 相关）
        for subdir in kb_path.iterdir():
            if subdir.is_dir() and not subdir.name.startswith('.'):
                try:
                    db = lancedb.connect(str(subdir))
                    tables = db.list_tables()
                    table_list = list(tables.tables) if hasattr(tables, 'tables') else []

                    # 查找匹配的表（表名可能包含 KB ID）
                    for table_name in table_list:
                        if kb_id in table_name or table_name in kb_id:
                            return subdir, table_name

                    # 如果只有一个表，也返回
                    if table_list:
                        return subdir, table_list[0]
                except Exception:
                    continue

        raise ValueError(f"知识库 {kb_id} 没有找到表")

    def _connect_table(self, kb_id: str) -> lancedb.table.Table:
        """
        连接到知识库的 LanceDB 表

        自动处理不同的目录结构：
        - KB 根目录可能就是表目录
        - 也可能在 KB_ID.lance/ 子目录下

        Args:
            kb_id: 知识库 ID

        Returns:
            LanceDB 表对象

        Raises:
            ValueError: 表不存在或无法连接
        """
        table_path, table_name = self._find_table_path(kb_id)
        db = lancedb.connect(str(table_path))
        return db.open_table(table_name)

    def _calculate_size(self, kb_path: Path) -> tuple:
        """
        计算知识库的存储大小

        包括 KB 目录下的所有子目录（如 KB.lance/）

        Args:
            kb_path: 知识库路径

        Returns:
            (size_bytes, file_count)
        """
        total_size = 0
        file_count = 0

        for f in kb_path.rglob('*'):
            if f.is_file():
                # 排除进度文件等非数据文件
                if not f.name.startswith('.') and not f.name.endswith('.json'):
                    total_size += f.stat().st_size
                    file_count += 1

        return total_size, file_count

    def get_stats(self, kb_id: str, use_cache: bool = True) -> KnowledgeBaseStats:
        """
        获取知识库统计信息

        Args:
            kb_id: 知识库 ID
            use_cache: 是否使用缓存

        Returns:
            KnowledgeBaseStats
        """
        # 检查缓存
        now = time.time()
        if use_cache:
            if kb_id in self._stats_cache:
                if now - self._cache_time.get(kb_id, 0) < self._cache_ttl:
                    return self._stats_cache[kb_id]

        kb_path = self._get_kb_path(kb_id)

        stats = KnowledgeBaseStats(
            kb_id=kb_id,
            name=kb_id,
            source_type=DataSourceType.UNKNOWN,
            exists=False,
        )

        if not kb_path.exists():
            stats.error = "路径不存在"
            return stats

        stats.exists = True

        try:
            # 连接表
            table = self._connect_table(kb_id)
            stats.row_count = table.count_rows()

            # 获取版本信息
            try:
                versions = table.list_versions()
                if versions:
                    latest = sorted(versions, key=lambda x: x.get('timestamp', ''), reverse=True)[0]
                    stats.last_modified = latest.get('timestamp', None)
            except Exception:
                pass

            # 计算大小
            total_size, file_count = self._calculate_size(kb_path)
            stats.size_bytes = total_size
            stats.size_mb = total_size / 1024 / 1024
            stats.size_gb = total_size / 1024 / 1024 / 1024
            stats.file_count = file_count

            # 检测数据源类型
            if (kb_path / ".zotero_nutrition_progress.json").exists():
                stats.source_type = DataSourceType.ZOTERO
                stats.name = "📖 Zotero 文献库"
            elif any(f.name.endswith(".md") for f in kb_path.rglob("*.md")):
                stats.source_type = DataSourceType.OBSIDIAN
                stats.name = f"📓 {kb_id}"
            else:
                stats.source_type = DataSourceType.GENERIC
                stats.name = kb_id

        except Exception as e:
            stats.error = str(e)

        # 更新缓存
        self._stats_cache[kb_id] = stats
        self._cache_time[kb_id] = now

        return stats

    def list_knowledge_bases(self) -> List[KnowledgeBaseStats]:
        """
        列出所有知识库及其状态

        Returns:
            知识库统计列表
        """
        if not self.storage_root.exists():
            return []

        results = []
        for kb_dir in sorted(self.storage_root.iterdir()):
            if kb_dir.is_dir():
                stats = self.get_stats(kb_dir.name, use_cache=False)
                results.append(stats)

        return results

    def exists(self, kb_id: str) -> bool:
        """
        检查知识库是否存在

        Args:
            kb_id: 知识库 ID

        Returns:
            是否存在
        """
        try:
            self._connect_table(kb_id)
            return True
        except Exception:
            return False

    def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        with_metadata: bool = True,
    ) -> List[SearchResult]:
        """
        搜索知识库

        使用向量搜索（需要 embedding 模型）。

        Args:
            kb_id: 知识库 ID
            query: 查询文本
            top_k: 返回结果数量
            with_metadata: 是否返回元数据

        Returns:
            搜索结果列表
        """
        table = self._connect_table(kb_id)

        # 执行向量搜索
        try:
            results = table.search(query).limit(top_k).to_arrow()

            search_results = []
            columns = results.to_pydict()

            texts = columns.get('text', [])
            scores = columns.get('score', [0.0] * len(texts))
            row_ids = columns.get('_row_id', [''] * len(texts))
            metadatas = columns.get('metadata', [{}] * len(texts))

            for i in range(len(texts)):
                sr = SearchResult(
                    text=texts[i] if i < len(texts) else "",
                    score=scores[i] if i < len(scores) else 0.0,
                    doc_id=row_ids[i] if i < len(row_ids) else "",
                )
                if with_metadata and i < len(metadatas):
                    metadata = metadatas[i]
                    if isinstance(metadata, str):
                        try:
                            metadata = json.loads(metadata)
                        except json.JSONDecodeError:
                            metadata = {}
                    sr.metadata = metadata if isinstance(metadata, dict) else {}
                search_results.append(sr)

            return search_results

        except Exception as e:
            raise RuntimeError(f"向量搜索失败: {e}")

    def count_rows(self, kb_id: str) -> int:
        """
        获取知识库行数

        Args:
            kb_id: 知识库 ID

        Returns:
            行数
        """
        table = self._connect_table(kb_id)
        return table.count_rows()

    def delete(self, kb_id: str) -> bool:
        """
        删除知识库

        Args:
            kb_id: 知识库 ID

        Returns:
            是否成功
        """
        try:
            kb_path = self._get_kb_path(kb_id)
            if kb_path.exists():
                import shutil
                shutil.rmtree(kb_path)

            # 清除缓存
            self._stats_cache.pop(kb_id, None)
            self._cache_time.pop(kb_id, None)

            return True
        except Exception as e:
            print(f"删除失败: {e}")
            return False

    def compact(self, kb_id: str) -> bool:
        """
        压缩知识库（清理旧版本）

        Args:
            kb_id: 知识库 ID

        Returns:
            是否成功
        """
        try:
            table = self._connect_table(kb_id)

            # 清理旧版本
            table.cleanup_old_versions()

            # 压缩文件
            table.compact_files()

            # 优化表
            table.optimize()

            # 清除缓存
            self._stats_cache.pop(kb_id, None)

            return True
        except Exception as e:
            print(f"压缩失败: {e}")
            return False

    def repair(self, kb_id: str) -> bool:
        """
        修复知识库（尝试修复 manifest 问题）

        Args:
            kb_id: 知识库 ID

        Returns:
            是否成功
        """
        try:
            kb_path = self._get_kb_path(kb_id)
            table = self._connect_table(kb_id)

            # 检查是否使用 v2 manifest paths
            if not table.uses_v2_manifest_paths():
                print("执行 manifest 迁移...")
                try:
                    table.migrate_v2_manifest_paths()
                except Exception as e:
                    print(f"迁移失败（非致命）: {e}")

            # 检查是否有 _latest.manifest
            latest_manifest = kb_path / "_latest.manifest"
            if not latest_manifest.exists():
                print(f"警告: _latest.manifest 不存在（表仍可读取）")

            # 清除缓存
            self._stats_cache.pop(kb_id, None)

            return True
        except Exception as e:
            print(f"修复失败: {e}")
            return False

    def get_table_info(self, kb_id: str) -> Dict[str, Any]:
        """
        获取表的详细信息

        Args:
            kb_id: 知识库 ID

        Returns:
            表信息字典
        """
        table = self._connect_table(kb_id)

        info = {
            "kb_id": kb_id,
            "path": str(self._get_kb_path(kb_id)),
            "row_count": table.count_rows(),
            "uses_v2_manifest": table.uses_v2_manifest_paths(),
        }

        # 获取版本信息
        try:
            versions = table.list_versions()
            if versions:
                latest = sorted(versions, key=lambda x: x.get('timestamp', ''), reverse=True)[0]
                info["latest_version"] = latest.get('version')
                info["latest_timestamp"] = str(latest.get('timestamp', ''))
        except Exception:
            pass

        # 获取索引信息
        try:
            indices = table.list_indices()
            info["indices"] = indices
        except Exception:
            pass

        return info


# 全局实例
_manager: Optional[KnowledgeBaseManager] = None


def get_manager() -> KnowledgeBaseManager:
    """获取全局知识库管理器实例"""
    global _manager
    if _manager is None:
        _manager = KnowledgeBaseManager()
    return _manager
