"""
知识库分类器 - 使用规则或 LLM 动态分类新文件夹
"""

import json
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from kb.database import init_category_rule_db


# LLM 分类提示词
CLASSIFICATION_PROMPT = """你是一个知识库分类专家。

## 你的任务
给定一个新文件夹的路径和描述，将其分类到最合适的知识库。

## 现有知识库及其特征

{knowledge_bases_info}

## 分类规则
1. 优先匹配明确的文件夹路径（如 "技术理论及方法" → 猪营养技术库）
2. 优先匹配标签（如 #猪营养 → 猪营养技术库）
3. 如果都不匹配，根据内容主题判断

## 注意事项
- 只选择一个最匹配的知识库
- 如果不确定，选择主题最接近的
- 不要创建新知识库

## 输出格式
JSON格式：
{{
    "kb_id": "知识库ID",
    "confidence": 0.0-1.0,
    "reason": "分类理由"
}}

## 新文件夹信息
- 路径: {folder_path}
- 描述: {folder_description}

请返回分类结果（只返回JSON，不要其他内容）："""


class CategoryClassifier:
    """知识库分类器"""

    def __init__(self):
        self.rule_db = init_category_rule_db()
        self._llm = None
        self._llm_available = True

    def _init_llm(self) -> bool:
        """初始化 LLM，返回是否成功"""
        if self._llm is not None:
            return self._llm_available

        try:
            from llamaindex_study.ollama_utils import create_llm
            from llamaindex_study.config import get_settings

            settings = get_settings()

            if not settings.siliconflow_api_key:
                print("   ⚠️  LLM 分类不可用: SILICONFLOW_API_KEY 未设置")
                self._llm_available = False
                return False

            self._llm = create_llm(model_id=None)
            self._llm_available = True
            return True
        except Exception as e:
            print(f"   ⚠️  LLM 初始化失败: {e}")
            import traceback

            traceback.print_exc()
            self._llm_available = False
            return False

    def get_knowledge_bases_info(self) -> List[Dict[str, Any]]:
        """获取所有知识库及其规则"""
        rules = self.rule_db.get_all_rules()

        # 按 kb_id 分组
        kb_rules: Dict[str, List[Dict]] = {}
        for rule in rules:
            kb_id = rule["kb_id"]
            if kb_id not in kb_rules:
                kb_rules[kb_id] = []
            kb_rules[kb_id].append(rule)

        return kb_rules

    def format_knowledge_bases_for_prompt(self) -> str:
        """格式化知识库信息用于提示词"""
        kb_rules = self.get_knowledge_bases_info()

        lines = []
        for kb_id, rules in kb_rules.items():
            # 获取文件夹路径规则
            folder_rules = [r for r in rules if r["rule_type"] == "folder_path"]
            # 获取标签规则
            tag_rules = [r for r in rules if r["rule_type"] == "tag"]

            info = f"- ID: {kb_id}\n"
            if folder_rules:
                info += f"  文件夹: {', '.join(r['pattern'] for r in folder_rules)}\n"
            if tag_rules:
                info += f"  标签: {', '.join(r['pattern'] for r in tag_rules)}"

            lines.append(info)

        return "\n\n".join(lines) if lines else "（暂无分类规则）"

    def classify_folder_llm(
        self,
        folder_path: str,
        folder_description: str = "",
    ) -> Dict[str, Any]:
        """
        使用 LLM 分类文件夹

        Args:
            folder_path: 文件夹路径
            folder_description: 文件夹描述（可以是文件夹名、包含文件列表等）

        Returns:
            分类结果 {kb_id, confidence, reason}
        """
        # 初始化 LLM
        if not self._init_llm():
            return {
                "kb_id": None,
                "confidence": 0.0,
                "reason": "LLM 服务不可用",
            }

        prompt = CLASSIFICATION_PROMPT.format(
            knowledge_bases_info=self.format_knowledge_bases_for_prompt(),
            folder_path=folder_path,
            folder_description=folder_description or "无",
        )

        try:
            # 使用 chat 模式
            from llama_index.core.llms import ChatMessage

            messages = [
                ChatMessage(
                    role="system",
                    content="You are a knowledge base classification assistant. Respond with JSON only.",
                ),
                ChatMessage(role="user", content=prompt),
            ]
            response = self._llm.chat(messages)

            # 获取文本内容
            text = ""
            if hasattr(response, "message") and hasattr(response.message, "content"):
                text = response.message.content
            elif hasattr(response, "text"):
                text = response.text

            if not text.strip():
                return {
                    "kb_id": None,
                    "confidence": 0.0,
                    "reason": "LLM 返回空响应",
                }

            # 解析 JSON 响应
            json_match = re.search(r"\{[^}]+\}", text)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "kb_id": result.get("kb_id"),
                    "confidence": result.get("confidence", 0.5),
                    "reason": result.get("reason", ""),
                }
            else:
                return {
                    "kb_id": None,
                    "confidence": 0.0,
                    "reason": "无法解析 LLM 响应",
                }
        except Exception as e:
            print(f"   ⚠️  LLM 分类失败: {e}")
            return {
                "kb_id": None,
                "confidence": 0.0,
                "reason": f"分类失败: {e}",
            }

    def classify_folder_rules(
        self,
        folder_path: str,
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        使用规则分类文件夹（不调用 LLM）

        Args:
            folder_path: 文件夹路径
            tags: 文件夹中笔记的标签列表

        Returns:
            匹配的知识库 ID 或 None
        """
        # 1. 先尝试匹配文件夹路径
        folder_rules = self.rule_db.get_rules_by_type("folder_path")
        for rule in folder_rules:
            if rule["pattern"] in folder_path:
                return rule["kb_id"]

        # 2. 尝试匹配标签
        if tags:
            tag_rules = self.rule_db.get_rules_by_type("tag")
            for rule in tag_rules:
                for tag in tags:
                    if rule["pattern"] == tag:
                        return rule["kb_id"]

        return None


def get_or_create_kb_rules(kb_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    获取或创建知识库的分类规则

    Args:
        kb_id: 知识库 ID

    Returns:
        规则字典
    """
    rule_db = init_category_rule_db()
    rules = rule_db.get_rules_for_kb(kb_id)

    return {
        "folder_path": [r for r in rules if r["rule_type"] == "folder_path"],
        "tag": [r for r in rules if r["rule_type"] == "tag"],
    }
