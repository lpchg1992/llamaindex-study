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


def get_zotero_storage_root() -> Path:
    """获取 Zotero 存储根目录"""
    settings = get_settings()
    return Path(settings.zotero_persist_dir)


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

    @property
    def persist_dir(self) -> Path:
        """获取持久化目录路径
        
        Obsidian 知识库使用 get_storage_root()
        Zotero 知识库使用 get_zotero_storage_root()
        """
        # Zotero 知识库的 persist_name 以 zotero_ 开头
        if self.id.startswith("zotero_"):
            return get_zotero_storage_root() / self.id
        
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
        }


# ==================== 知识库定义（默认值，用于初始化数据库） ====================
# 注意：source_paths 使用相对于 vault_root 的相对路径
# 可通过环境变量配置实际路径：OBSIDIAN_VAULT_ROOT

KNOWLEDGE_BASES: List[KnowledgeBase] = [
    KnowledgeBase(
        id="hitech_history",
        name="🏢 高新历史项目库",
        description="高新技术企业历史研发项目资料（2022-2024）",
        source_paths=[
            "高新历史/2022年",
            "高新历史/2023年",
            "高新历史/2024年",
        ],
        persist_name="hitech_history",
        tags=["高新", "研发项目", "历史资料"],
        source_tags=["#高新", "#研发", "#项目"],
    ),
    KnowledgeBase(
        id="swine_nutrition",
        name="🐷 猪营养技术库",
        description="猪营养学理论、饲料原料知识、配方技术",
        source_paths=[
            "技术理论及方法",
            "饲料原料笔记",
        ],
        persist_name="kb_swine_nutrition",
        tags=["猪营养", "饲料配方", "技术理论"],
        source_tags=[
            "#猪营养", "#饲料", "#配方", "#原料",
            "#swine", "#nutrition", "#feed",
            "#消化率", "#净能", "#氨基酸",
        ],
    ),
    KnowledgeBase(
        id="rd_experiments",
        name="📊 试验研发库",
        description="历史试验记录、研发日志、工作日志",
        source_paths=[
            "试验研发",
            "工作日志",
        ],
        persist_name="kb_rd_experiments",
        tags=["试验", "研发", "工作日志"],
        source_tags=[
            "#试验", "#研发", "#实验", "#研究",
            "#工作日志", "#日报", "#周报",
            "#experiment", "#trial", "#study",
        ],
    ),
    KnowledgeBase(
        id="hitech_projects",
        name="📝 项目申报库",
        description="高新技术企业认定项目申报材料",
        source_paths=[
            "高新技术企业专题工作",
        ],
        persist_name="kb_hitech_projects",
        tags=["高新年", "项目申报", "材料"],
        source_tags=[
            "#高新年", "#项目申报", "#高新技术",
            "#hitech", "#project",
        ],
    ),
    KnowledgeBase(
        id="tech_tools",
        name="💻 技术工具库",
        description="IT技术、AI工具使用、服务器配置、编程技能",
        source_paths=[
            "IT",
        ],
        persist_name="kb_tech_tools",
        tags=["IT", "AI工具", "编程", "服务器"],
        source_tags=[
            "#IT", "#编程", "#服务器", "#AI工具",
            "#python", "#编程", "#docker", "#linux",
            "#code", "#programming", "#server",
            "#技术", "#工具", "#软件",
        ],
    ),
    KnowledgeBase(
        id="academic",
        name="📚 学术资料库",
        description="博士专项学习资料、收藏的学术文章和研究文献",
        source_paths=[
            "博士专项",
            "知识库/收藏知识库/AI",
            "知识库/收藏知识库/农业",
        ],
        persist_name="kb_academic",
        tags=["学术", "博士", "AI研究"],
        source_tags=[
            "#学术", "#论文", "#博士", "#研究",
            "#论文笔记", "#文献", "#AI研究",
            "#academic", "#research", "#paper",
            "#PhD", "#博士论文",
        ],
    ),
    KnowledgeBase(
        id="industry_news",
        name="🌐 行业资讯库",
        description="AI新闻日报、畜牧行业资讯、市场动态",
        source_paths=[
            "知识库/AI 行业新闻日报",
            "知识库/AI 行业学术日报",
            "知识库/收藏知识库/新闻",
        ],
        persist_name="kb_industry_news",
        tags=["行业新闻", "AI日报", "畜牧资讯"],
        source_tags=[
            "#新闻", "#日报", "#资讯", "#行业动态",
            "#news", "#daily", "#industry",
            "#AI新闻", "#畜牧", "#市场",
        ],
    ),
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
    """知识库注册表
    
    支持从数据库加载分类规则（folder_path, tag）。
    优先使用数据库中的规则，如果数据库为空则使用硬编码的 KNOWLEDGE_BASES。
    """

    def __init__(self) -> None:
        self._bases: Dict[str, KnowledgeBase] = {kb.id: kb for kb in KNOWLEDGE_BASES}
        self._rule_db: Optional[Any] = None
        self._rules_loaded: bool = False
    
    @property
    def rule_db(self) -> Any:
        """延迟加载规则数据库"""
        if self._rule_db is None:
            from kb.database import init_category_rule_db
            self._rule_db = init_category_rule_db()
        return self._rule_db
    
    def _load_rules_from_db(self) -> None:
        """从数据库加载分类规则到 KnowledgeBase"""
        if self._rules_loaded:
            return
        
        try:
            all_rules = self.rule_db.get_all_rules()
            
            if all_rules:
                # 按 kb_id 分组规则
                kb_rules: Dict[str, Dict[str, List[str]]] = {}
                for rule in all_rules:
                    kb_id = rule["kb_id"]
                    rule_type = rule["rule_type"]
                    pattern = rule["pattern"]
                    
                    if kb_id not in kb_rules:
                        kb_rules[kb_id] = {"folder_path": [], "tag": []}
                    
                    if rule_type in kb_rules[kb_id]:
                        kb_rules[kb_id][rule_type].append(pattern)
                
                # 更新 KnowledgeBase 的 source_paths 和 source_tags
                for kb_id, rules in kb_rules.items():
                    if kb_id in self._bases:
                        kb = self._bases[kb_id]
                        if rules["folder_path"]:
                            kb.source_paths = rules["folder_path"]
                        if rules["tag"]:
                            kb.source_tags = rules["tag"]
                
                logger.info(f"从数据库加载了 {len(all_rules)} 条分类规则")
            else:
                logger.debug("数据库暂无分类规则，使用默认配置")
        except Exception as e:
            logger.warning(f"加载分类规则失败: {e}")
        
        self._rules_loaded = True
    
    def get(self, kb_id: str) -> Optional[KnowledgeBase]:
        """根据 ID 获取知识库"""
        self._load_rules_from_db()
        return self._bases.get(kb_id)

    def list_all(self) -> List[KnowledgeBase]:
        """列出所有知识库"""
        self._load_rules_from_db()
        return list(self._bases.values())

    def get_by_tag(self, tag: str) -> List[KnowledgeBase]:
        """根据标签查找知识库"""
        self._load_rules_from_db()
        return [kb for kb in self._bases.values() if tag in kb.tags]

    def exists(self, kb_id: str) -> bool:
        """检查知识库是否存在"""
        return kb_id in self._bases

    def is_indexed(self, kb_id: str) -> bool:
        """检查知识库是否已有索引"""
        kb = self.get(kb_id)
        if kb is None:
            return False
        # LlamaIndex 保存为 default__vector_store.json
        vector_store = kb.persist_dir / "default__vector_store.json"
        return vector_store.exists()
    
    def seed_rules_to_db(self) -> int:
        """将硬编码的配置同步到数据库"""
        try:
            kb_configs = [kb.to_dict() for kb in KNOWLEDGE_BASES]
            count = self.rule_db.seed_initial_rules(kb_configs)
            self._rules_loaded = False  # 重置，下次重新加载
            return count
        except Exception as e:
            logger.warning(f"同步规则到数据库失败: {e}")
            return 0


# 全局注册表实例
registry = KnowledgeBaseRegistry()


def get_registry() -> KnowledgeBaseRegistry:
    """获取知识库注册表实例"""
    return registry
