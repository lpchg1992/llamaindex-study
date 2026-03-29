"""
Obsidian 知识库配置

定义 Obsidian vault 中不同文件夹到知识库的映射关系
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ObsidianKnowledgeMapping:
    """Obsidian 知识库映射"""
    kb_id: str                    # 知识库 ID
    name: str                   # 知识库名称
    folders: List[str]          # 匹配的文件夹路径（支持子目录匹配）
    tags: List[str] = field(default_factory=list)  # 匹配的标签
    description: str = ""       # 描述


# Obsidian 知识库映射配置
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
    ObsidianKnowledgeMapping(
        kb_id="obsidian_main",
        name="📓 Obsidian 主库",
        folders=[],  # 默认知识库，匹配所有文件
        tags=[],
        description="Obsidian 所有笔记（默认库）",
    ),
]


def find_kb_by_path(relative_path: str, mappings: List[ObsidianKnowledgeMapping] = None) -> List[str]:
    """
    根据文件路径查找匹配的知识库
    
    Args:
        relative_path: 相对于 vault 根目录的路径
        mappings: 映射配置，默认使用 OBSIDIAN_KB_MAPPINGS
        
    Returns:
        匹配的知识库 ID 列表
    """
    if mappings is None:
        mappings = OBSIDIAN_KB_MAPPINGS
    
    matched = []
    
    for mapping in mappings:
        for folder in mapping.folders:
            # 支持子目录匹配
            if folder in relative_path or relative_path.startswith(folder + "/"):
                if mapping.kb_id not in matched:
                    matched.append(mapping.kb_id)
                break
    
    return matched


def find_kb_by_tags(tags: List[str], mappings: List[ObsidianKnowledgeMapping] = None) -> List[str]:
    """
    根据标签查找匹配的知识库
    
    Args:
        tags: 文件的标签列表
        mappings: 映射配置
        
    Returns:
        匹配的知识库 ID 列表
    """
    if mappings is None:
        mappings = OBSIDIAN_KB_MAPPINGS
    
    matched = []
    
    for mapping in mappings:
        for source_tag in mapping.tags:
            for doc_tag in tags:
                if source_tag == doc_tag or source_tag in doc_tag or doc_tag in source_tag:
                    if mapping.kb_id not in matched:
                        matched.append(mapping.kb_id)
                    break
    
    return matched


def classify_note(relative_path: str, tags: List[str]) -> List[str]:
    """
    对笔记进行分类
    
    Args:
        relative_path: 相对路径
        tags: 标签列表
        
    Returns:
        匹配的知识库 ID 列表（优先按路径，再按标签）
    """
    # 1. 按路径匹配
    path_matches = find_kb_by_path(relative_path)
    
    # 2. 按标签匹配
    tag_matches = find_kb_by_tags(tags)
    
    # 3. 合并结果
    result = path_matches.copy()
    for kb_id in tag_matches:
        if kb_id not in result:
            result.append(kb_id)
    
    # 4. 如果没有匹配，放入默认库
    if not result:
        result = ["obsidian_main"]
    
    return result
