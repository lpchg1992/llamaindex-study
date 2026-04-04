"""
知识库注册表

定义所有知识库的配置，包括：
- 来源路径（Obsidian 目录）
- 持久化路径
- 名称、描述等元数据

支持从数据库加载分类规则。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 存储配置常量（可配置）
DEFAULT_STORAGE_ROOT = Path.home() / ".llamaindex" / "storage"
DEFAULT_VAULT_ROOT = Path.home() / "Documents" / "Obsidian Vault"


def get_storage_root() -> Path:
    """获取存储根目录（延迟加载，支持环境变量配置）"""
    settings = get_settings()
    return Path(settings.persist_dir)


def get_vault_root() -> Path:
    """获取 Obsidian Vault 根目录"""
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)

    vault_root = os.getenv("OBSIDIAN_VAULT_ROOT")
    if vault_root:
        return Path(vault_root)

    return DEFAULT_VAULT_ROOT


@dataclass
class KnowledgeBase:
    """知识库定义"""

    id: str  # 唯一标识（如 "swine_nutrition"）
    name: str  # 显示名称（如 "猪营养技术库"）
    description: str  # 描述
    source_paths: List[str]  # Obsidian 源路径列表（相对于 vault_root）
    persist_name: str  # 存储目录名
    tags: List[str] = field(default_factory=list)  # 标签（描述用）
    source_tags: List[str] = field(default_factory=list)  # 用于分类的标签列表
    topics: List[str] = field(
        default_factory=list
    )  # 主题关键词（帮助 LLM 理解 KB 内容）

    @property
    def persist_dir(self) -> Path:
        """获取持久化目录路径"""
        return get_storage_root() / self.persist_name

    def source_paths_abs(self, vault_root: Optional[Path] = None) -> List[Path]:
        """获取源路径的绝对路径列表"""
        if vault_root is None:
            vault_root = get_vault_root()
        return [vault_root / p for p in self.source_paths]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_paths": self.source_paths,
            "persist_name": self.persist_name,
            "tags": self.tags,
            "source_tags": self.source_tags,
            "topics": self.topics,
        }


# ==================== 知识库定义（默认值，用于初始化数据库） ====================
# 注意：source_paths 使用相对于 vault_root 的相对路径
# 可通过环境变量配置实际路径：OBSIDIAN_VAULT_ROOT
# 已清理：只保留 zotero_nutrition

KNOWLEDGE_BASES: List[KnowledgeBase] = [
    KnowledgeBase(
        id="zotero_nutrition",
        name="📚 Zotero 营养文献库",
        description="Zotero 导入的营养学相关文献",
        source_paths=[
            "营养饲料理论",
        ],
        persist_name="zotero_nutrition",
        tags=["Zotero", "文献", "营养学"],
        source_tags=["#zotero", "#文献", "#营养"],
    ),
]


class KnowledgeBaseRegistry:
    """知识库注册表（从数据库加载）"""

    def __init__(self) -> None:
        self._bases: Dict[str, KnowledgeBase] = {}
        self._loaded: bool = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._bases.clear()

        try:
            from kb.database import init_kb_meta_db

            db = init_kb_meta_db()
            all_kbs = db.get_all(active_only=True)
            if all_kbs:
                for row in all_kbs:
                    kb = self._row_to_kb(row)
                    if kb:
                        self._bases[kb.id] = kb
                logger.debug(f"从数据库加载了 {len(self._bases)} 个知识库")
            else:
                logger.debug("数据库为空，无知识库")
        except Exception as e:
            logger.warning(f"从数据库加载失败: {e}")

        self._loaded = True

    def _row_to_kb(self, row: Dict[str, Any]) -> Optional[KnowledgeBase]:
        try:
            return KnowledgeBase(
                id=row["kb_id"],
                name=row.get("name", row["kb_id"]),
                description=row.get("description", ""),
                source_paths=row.get("source_paths", []),
                persist_name=row.get("persist_path", "").split("/")[-1]
                if row.get("persist_path")
                else row["kb_id"],
                tags=row.get("tags", []),
                source_tags=row.get("source_tags", []),
            )
        except Exception:
            return None

    def get(self, kb_id: str) -> Optional[KnowledgeBase]:
        self._ensure_loaded()
        return self._bases.get(kb_id)

    def list_all(self) -> List[KnowledgeBase]:
        self._ensure_loaded()
        return list(self._bases.values())

    def get_by_tag(self, tag: str) -> List[KnowledgeBase]:
        self._ensure_loaded()
        return [kb for kb in self._bases.values() if tag in kb.tags]

    def exists(self, kb_id: str) -> bool:
        self._ensure_loaded()
        return kb_id in self._bases

    def is_indexed(self, kb_id: str) -> bool:
        kb = self.get(kb_id)
        if kb is None:
            return False
        vector_store = kb.persist_dir / "default__vector_store.json"
        return vector_store.exists()


registry = KnowledgeBaseRegistry()


def get_registry() -> KnowledgeBaseRegistry:
    """获取知识库注册表实例"""
    return registry


def seed_all_to_database() -> int:
    """将所有注册表知识库迁移到数据库"""
    from kb.database import init_kb_meta_db

    kb_dicts = [kb.to_dict() for kb in KNOWLEDGE_BASES]
    db = init_kb_meta_db()
    return db.seed_from_registry(kb_dicts)
