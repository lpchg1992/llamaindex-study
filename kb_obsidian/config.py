"""
Obsidian 知识库配置

支持从数据库加载分类规则，也保留硬编码配置作为默认值。
"""

from dataclasses import dataclass, field
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
    """Obsidian 映射注册表"""

    def __init__(self):
        self._mappings: Dict[str, ObsidianKnowledgeMapping] = {
            m.kb_id: m for m in OBSIDIAN_KB_MAPPINGS
        }

    def get(self, kb_id: str) -> Optional[ObsidianKnowledgeMapping]:
        """获取映射"""
        return self._mappings.get(kb_id)

    def list_all(self) -> List[ObsidianKnowledgeMapping]:
        """列出所有映射"""
        return list(self._mappings.values())


# 全局实例
mapping_registry = ObsidianMappingRegistry()
