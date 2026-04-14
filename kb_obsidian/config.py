"""
Obsidian 知识库配置

支持从数据库加载分类规则，也保留硬编码配置作为默认值。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class ObsidianKnowledgeMapping:
    """Obsidian 知识库映射"""
    kb_id: str                    # 知识库 ID
    name: str                   # 知识库名称
    folders: List[str] = field(default_factory=list)  # 匹配的文件夹路径
    tags: List[str] = field(default_factory=list)  # 匹配的标签
    description: str = ""       # 描述
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "kb_id": self.kb_id,
            "name": self.name,
            "folders": self.folders,
            "tags": self.tags,
            "description": self.description,
        }


# Obsidian 知识库映射配置（默认值，用于初始化数据库）
OBSIDIAN_KB_MAPPINGS: List[ObsidianKnowledgeMapping] = [
    ObsidianKnowledgeMapping(
        kb_id="swine_nutrition",
        name="🐷 猪营养技术库",
        folders=[
            "技术理论及方法",
            "饲料原料笔记",
            "质量控制",
        ],
        tags=["#猪营养", "#饲料配方", "#原料", "#营养需要", "#日粮", "#净能", "#氨基酸"],
        description="猪营养学理论、饲料原料知识、配方技术",
    ),
    ObsidianKnowledgeMapping(
        kb_id="rd_experiments",
        name="📊 试验研发库",
        folders=[
            "试验研发",
            "工作日志",
            "各类会议",
        ],
        tags=["#试验", "#研发", "#工作日志", "#实验"],
        description="历史试验记录、研发日志、会议纪要",
    ),
    ObsidianKnowledgeMapping(
        kb_id="hitech_projects",
        name="📝 高新项目库",
        folders=[
            "高新技术企业专题工作",
            "公司经营运营相关",
            "产品设计管理工作",
            "产品市场工作",
        ],
        tags=["#高新", "#项目申报", "#高新技术"],
        description="高新技术企业认定项目申报材料",
    ),
    ObsidianKnowledgeMapping(
        kb_id="academic",
        name="📚 学术资料库",
        folders=[
            "博士专项",
            "知识库/收藏知识库",
        ],
        tags=["#学术", "#论文", "#博士", "#研究"],
        description="博士专项学习资料、收藏的学术文章",
    ),
    ObsidianKnowledgeMapping(
        kb_id="industry_news",
        name="🌐 行业资讯库",
        folders=[
            "知识库/AI 行业新闻日报",
        ],
        tags=["#新闻", "#日报", "#资讯", "#行业动态"],
        description="AI 新闻日报、畜牧行业资讯",
    ),
    ObsidianKnowledgeMapping(
        kb_id="tech_tools",
        name="💻 技术工具库",
        folders=[
            "IT",
            "copilot",
            "Z_Copilot",
        ],
        tags=["#IT", "#编程", "#服务器", "#AI工具"],
        description="IT技术、AI工具使用、服务器配置",
    ),
]


class ObsidianMappingRegistry:
    """Obsidian 映射注册表（支持数据库加载）"""
    
    def __init__(self):
        self._mappings: Dict[str, ObsidianKnowledgeMapping] = {
            m.kb_id: m for m in OBSIDIAN_KB_MAPPINGS
        }
        self._db_loaded = False
    
    @property
    def rule_db(self):
        """延迟加载规则数据库"""
        from kb_core.database import init_category_rule_db
        return init_category_rule_db()
    
    def _load_from_db(self):
        """从数据库加载映射"""
        if self._db_loaded:
            return
        
        try:
            all_rules = self.rule_db.get_all_rules()
            
            if all_rules:
                # 按 kb_id 分组
                kb_rules: Dict[str, Dict[str, List[str]]] = {}
                for rule in all_rules:
                    kb_id = rule["kb_id"]
                    rule_type = rule["rule_type"]
                    pattern = rule["pattern"]
                    
                    if kb_id not in kb_rules:
                        kb_rules[kb_id] = {"folder_path": [], "tag": []}
                    
                    # 转换规则类型
                    if rule_type == "folder_path":
                        kb_rules[kb_id]["folder_path"].append(pattern)
                    elif rule_type == "tag":
                        kb_rules[kb_id]["tag"].append(pattern)
                
                # 更新映射
                for kb_id, rules in kb_rules.items():
                    if kb_id in self._mappings:
                        if rules["folder_path"]:
                            self._mappings[kb_id].folders = rules["folder_path"]
                        if rules["tag"]:
                            self._mappings[kb_id].tags = rules["tag"]
        except Exception as e:
            print(f"   ⚠️  加载映射规则失败: {e}")
        
        self._db_loaded = True
    
    def get(self, kb_id: str) -> Optional[ObsidianKnowledgeMapping]:
        """获取映射"""
        self._load_from_db()
        return self._mappings.get(kb_id)
    
    def list_all(self) -> List[ObsidianKnowledgeMapping]:
        """列出所有映射"""
        self._load_from_db()
        return list(self._mappings.values())
    
    def find_by_path(self, relative_path: str) -> List[str]:
        """根据路径查找匹配的知识库"""
        self._load_from_db()
        
        matched = []
        for mapping in self._mappings.values():
            for folder in mapping.folders:
                if folder in relative_path or relative_path.startswith(folder + "/"):
                    if mapping.kb_id not in matched:
                        matched.append(mapping.kb_id)
                    break
        
        return matched
    
    def find_by_tags(self, tags: List[str]) -> List[str]:
        """根据标签查找匹配的知识库"""
        self._load_from_db()
        
        matched = []
        for mapping in self._mappings.values():
            for source_tag in mapping.tags:
                for doc_tag in tags:
                    if source_tag == doc_tag or source_tag in doc_tag:
                        if mapping.kb_id not in matched:
                            matched.append(mapping.kb_id)
                        break
        
        return matched
    
    def classify(self, relative_path: str, tags: List[str]) -> List[str]:
        """对笔记进行分类"""
        # 1. 按路径匹配
        path_matches = self.find_by_path(relative_path)
        
        # 2. 按标签匹配
        tag_matches = self.find_by_tags(tags)
        
        # 3. 合并结果
        result = path_matches.copy()
        for kb_id in tag_matches:
            if kb_id not in result:
                result.append(kb_id)
        
        return result


# 全局实例
mapping_registry = ObsidianMappingRegistry()


def find_kb_by_path(relative_path: str) -> List[str]:
    """根据文件路径查找匹配的知识库"""
    return mapping_registry.find_by_path(relative_path)


def find_kb_by_tags(tags: List[str]) -> List[str]:
    """根据标签查找匹配的知识库"""
    return mapping_registry.find_by_tags(tags)


def classify_note(relative_path: str, tags: List[str]) -> List[str]:
    """对笔记进行分类"""
    return mapping_registry.classify(relative_path, tags)


def seed_mappings_to_db() -> int:
    """将硬编码配置同步到数据库"""
    rule_db = mapping_registry.rule_db
    count = 0
    
    for mapping in OBSIDIAN_KB_MAPPINGS:
        # 添加文件夹规则
        for i, folder in enumerate(mapping.folders):
            if rule_db.add_rule(
                kb_id=mapping.kb_id,
                rule_type="folder_path",
                pattern=folder,
                description=f"文件夹路径匹配: {folder}",
                priority=100 - i,
            ):
                count += 1
        
        # 添加标签规则
        for i, tag in enumerate(mapping.tags):
            if rule_db.add_rule(
                kb_id=mapping.kb_id,
                rule_type="tag",
                pattern=tag,
                description=f"标签匹配: {tag}",
                priority=50 - i,
            ):
                count += 1
    
    mapping_registry._db_loaded = False  # 重置，下次重新加载
    return count
