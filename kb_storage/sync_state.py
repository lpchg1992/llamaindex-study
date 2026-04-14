"""
同步状态管理器

支持两种存储方式：
1. SQLite 数据库（推荐）- 使用 kb/database.py
2. JSON 文件（向后兼容）

基于文件哈希的增量同步机制：
1. 记录每个文件的 hash 和修改时间
2. 检测文件变更、新增、删除
3. 支持增量更新和删除同步
"""

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set

from llama_index.core.schema import Document


@dataclass
class FileState:
    """文件同步状态"""
    file_path: str          # 相对于 vault 的路径
    absolute_path: str       # 绝对路径
    hash: str              # 文件内容 hash
    mtime: float           # 修改时间
    last_synced: float     # 最后同步时间
    doc_id: str           # 文档 ID（来自 LlamaIndex）

    @property
    def path(self) -> str:
        return self.file_path

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FileState":
        return cls(**data)


class SyncState:
    """
    同步状态管理器
    
    维护知识库中每个文件的同步状态，支持增量同步。
    
    使用 SQLite 数据库存储状态。
    """

    # 同步状态文件后缀（向后兼容）
    STATE_FILE = ".sync_state.json"

    def __init__(self, kb_id: str, persist_dir: Path, use_sqlite: bool = True):
        """
        初始化同步状态管理器
        
        Args:
            kb_id: 知识库 ID
            persist_dir: 持久化目录
            use_sqlite: 是否使用 SQLite（默认 True）
        """
        self.kb_id = kb_id
        self.persist_dir = Path(persist_dir)
        self.use_sqlite = use_sqlite

        # 内存中的状态：{file_path: FileState}
        self._states: Dict[str, FileState] = {}
        
        # SQLite 数据库操作
        self._sync_db = None
        
        if use_sqlite:
            self._init_sqlite()
        else:
            self._load_json()

    def _init_sqlite(self):
        """初始化 SQLite 数据库"""
        from kb_core.database import init_sync_db
        self._sync_db = init_sync_db()
        self._load_sqlite()

    def _load_sqlite(self):
        """从 SQLite 加载状态"""
        try:
            records = self._sync_db.get_records(self.kb_id)
            self._states = {
                r["file_path"]: FileState(
                    file_path=r["file_path"],
                    absolute_path="",  # SQLite 不存储这个字段
                    hash=r["hash"],
                    mtime=r["mtime"],
                    last_synced=r["last_synced"],
                    doc_id=r["doc_id"],
                )
                for r in records
            }
        except Exception as e:
            print(f"   ⚠️  从 SQLite 加载同步状态失败: {e}")
            self._states = {}

    def _load_json(self):
        """从 JSON 文件加载状态（向后兼容）"""
        state_file = self.persist_dir / self.STATE_FILE
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._states = {
                        path: FileState.from_dict(state)
                        for path, state in data.items()
                    }
            except Exception as e:
                print(f"   ⚠️  加载同步状态失败: {e}")
                self._states = {}

    def _save_json(self):
        """保存状态到 JSON 文件（向后兼容）"""
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.persist_dir / self.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {path: state.to_dict() for path, state in self._states.items()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"   ⚠️  保存同步状态失败: {e}")

    @staticmethod
    def compute_hash(file_path: Path) -> str:
        """计算文件的 MD5 hash"""
        hasher = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"   ⚠️  计算 hash 失败 {file_path}: {e}")
            return ""

    @staticmethod
    def compute_doc_hash(content: str) -> str:
        """计算文档内容的 hash"""
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def get_state(self, file_path: str) -> Optional[FileState]:
        """获取文件状态"""
        return self._states.get(file_path)

    def update_state(
        self,
        file_path: str,
        absolute_path: str,
        content: str,
        doc_id: str,
    ) -> FileState:
        """
        更新文件状态
        
        Args:
            file_path: 相对路径
            absolute_path: 绝对路径
            content: 文件内容
            doc_id: 文档 ID
        
        Returns:
            FileState
        """
        state = FileState(
            file_path=file_path,
            absolute_path=absolute_path,
            hash=self.compute_doc_hash(content),
            mtime=Path(absolute_path).stat().st_mtime if Path(absolute_path).exists() else time.time(),
            last_synced=time.time(),
            doc_id=doc_id,
        )
        self._states[file_path] = state

        # 持久化
        if self.use_sqlite and self._sync_db:
            self._sync_db.update_state(
                kb_id=self.kb_id,
                file_path=file_path,
                hash=state.hash,
                mtime=state.mtime,
                doc_id=doc_id,
            )
        else:
            self._save_json()

        return state

    def remove_state(self, file_path: str) -> Optional[FileState]:
        """
        移除文件状态
        
        Args:
            file_path: 相对路径
        
        Returns:
            被移除的 FileState 或 None
        """
        state = self._states.pop(file_path, None)
        
        if state:
            if self.use_sqlite and self._sync_db:
                self._sync_db.remove(self.kb_id, file_path)
            else:
                self._save_json()
        
        return state

    def has_changed(self, file_path: str, absolute_path: str, content: str) -> bool:
        """
        检查文件是否已变更
        
        Args:
            file_path: 相对路径
            absolute_path: 绝对路径
            content: 当前内容
        
        Returns:
            True 如果文件变更或新增
        """
        state = self._states.get(file_path)
        if state is None:
            return True  # 新文件
        
        current_hash = self.compute_doc_hash(content)
        if current_hash != state.hash:
            return True  # 内容变更
        
        # 检查文件是否被删除
        if not Path(absolute_path).exists():
            return True  # 文件已删除
        
        return False

    def detect_changes(
        self,
        current_files: List[Path],
        vault_root: Path,
    ) -> tuple:
        """
        检测文件变更
        
        Args:
            current_files: 当前 vault 中的文件列表
            vault_root: Vault 根目录
        
        Returns:
            (to_add, to_update, to_delete)
            - to_add: 需要新增的文件
            - to_update: 需要更新的文件
            - to_delete: 需要删除的文件（已从 vault 中移除）
        """
        to_add = []      # 新增文件
        to_update = []   # 更新文件
        to_delete = []   # 删除文件（doc_id 列表）
        
        # 当前 vault 中的文件路径集合
        current_paths = set()
        
        for file_path in current_files:
            rel_path = str(file_path.relative_to(vault_root))
            current_paths.add(rel_path)
            
            if not self.has_changed(rel_path, str(file_path), file_path.read_text(encoding="utf-8", errors="ignore")):
                continue  # 文件未变更
            
            state = self._states.get(rel_path)
            if state is None:
                to_add.append((rel_path, file_path))
            else:
                to_update.append((rel_path, file_path, state.doc_id))
        
        # 检测删除的文件
        for file_path, state in self._states.items():
            if file_path not in current_paths:
                to_delete.append((file_path, state.doc_id))
        
        return to_add, to_update, to_delete

    def get_doc_ids(self) -> List[str]:
        """获取所有已同步文档的 doc_id"""
        return [state.doc_id for state in self._states.values()]

    def get_doc_id_map(self) -> Dict[str, str]:
        """获取 file_path -> doc_id 的映射"""
        return {state.file_path: state.doc_id for state in self._states.items()}

    def clear(self):
        """清空所有状态"""
        self._states.clear()
        
        if self.use_sqlite and self._sync_db:
            self._sync_db.clear(self.kb_id)
        else:
            self._save_json()

    def cleanup_orphaned(self, valid_doc_ids: Set[str]):
        """
        清理孤立的文档记录
        
        Args:
            valid_doc_ids: 当前有效的 doc_id 集合
        """
        orphaned = []
        for file_path, state in self._states.items():
            if state.doc_id not in valid_doc_ids:
                orphaned.append((file_path, state.doc_id))
        
        for file_path, doc_id in orphaned:
            self.remove_state(file_path)
        
        if orphaned:
            print(f"   🗑️  清理了 {len(orphaned)} 条孤立记录")

    def get_stats(self) -> dict:
        """获取同步统计"""
        return {
            "total_files": len(self._states),
            "synced_files": len([s for s in self._states.values() if s.last_synced > 0]),
        }


class IncrementalSyncManager:
    """
    增量同步管理器
    
    协调多个知识库的增量同步。
    """

    def __init__(self, persist_root: Path):
        """
        初始化管理器
        
        Args:
            persist_root: 持久化根目录
        """
        self.persist_root = Path(persist_root)
        self._states: Dict[str, SyncState] = {}

    def get_state(self, kb_id: str, persist_dir: Path) -> SyncState:
        """
        获取知识库的同步状态
        
        Args:
            kb_id: 知识库 ID
            persist_dir: 持久化目录
        
        Returns:
            SyncState
        """
        if kb_id not in self._states:
            self._states[kb_id] = SyncState(kb_id, persist_dir)
        return self._states[kb_id]

    def get_all_stats(self) -> Dict[str, dict]:
        """获取所有知识库的同步统计"""
        return {kb_id: state.get_stats() for kb_id, state in self._states.items()}
