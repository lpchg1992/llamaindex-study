"""
关键词提取模块

从文档内容中提取关键词，帮助理解知识库主题。
支持 LLM 提取和统计方法提取。
"""

import re
from collections import Counter
from typing import List, Set

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class KeywordExtractor:
    """关键词提取器"""

    def __init__(self, min_freq: int = 2, max_keywords: int = 50):
        self.min_freq = min_freq
        self.max_keywords = max_keywords

    def extract_from_text(self, text: str) -> List[str]:
        text = self._clean_text(text)
        return self._extract_with_llm(text)

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"!\[\[.*?\]\]", "", text)
        text = re.sub(r"\[\[.*?\|.*?\]\]", "", text)
        text = re.sub(r"#+\s+", "", text)
        text = re.sub(r"\*\*+", "", text)
        text = re.sub(r"http\S+", "", text)
        text = re.sub(r"\[\d+\]", "", text)
        text = re.sub(r"---+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _extract_with_llm(self, text: str) -> List[str]:
        try:
            import httpx

            settings = get_settings()

            prompt = (
                "你是一个专业的知识库主题分析助手。请从以下文档内容中提取15-25个主题词。\n"
                "要求：\n"
                "1. 只提取专业术语、学术名词、具体概念（如蛋白质代谢、猪营养配方、线性规划等）\n"
                "2. 只提取名词性词汇，不要动词、形容词、副词、介词\n"
                "3. 优先提取能体现学科领域特色的专业词汇\n"
                "4. 用换行符分隔，每行一个词\n\n"
                "---文档内容---\n"
                f"{text[:4000]}\n"
                "---文档结束---\n\n"
                "主题词（每行一个）："
            )

            resp = httpx.post(
                f"{settings.siliconflow_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.siliconflow_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.siliconflow_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()

            keywords = []
            for line in result.split("\n"):
                line = line.strip().strip("0123456789.-、，、:：) ")
                if line and len(line) >= 2:
                    keywords.append(line)

            valid = [k for k in keywords if k.lower() not in self._get_stopwords()]
            filtered = [k for k in valid if not self._is_invalid_keyword(k)]
            return filtered[:20]

        except Exception as e:
            logger.warning(f"LLM 关键词提取失败: {e}")
            return []

    def _is_invalid_keyword(self, kw: str) -> bool:
        kw_lower = kw.lower()
        if len(kw) < 2:
            return True
        invalid_patterns = [
            "无法提取",
            "请提供",
            "请输入",
            "没有内容",
            "关键词",
            "文档内容",
            "内容为空",
            "无法识别",
        ]
        if any(p in kw_lower for p in invalid_patterns):
            return True
        if any(c in kw_lower for c in "，。：；？！''【】（）、"):
            return True
        return False

    @staticmethod
    def _get_stopwords() -> Set[str]:
        """获取停用词表"""
        return {
            "的",
            "了",
            "在",
            "是",
            "我",
            "有",
            "和",
            "就",
            "不",
            "人",
            "都",
            "一",
            "一个",
            "上",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "着",
            "没有",
            "看",
            "好",
            "自己",
            "这",
            "那",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "need",
            "dare",
            "ought",
            "used",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "under",
            "again",
            "further",
            "then",
            "once",
            "and",
            "but",
            "or",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "because",
            "how",
            "when",
            "where",
            "why",
            "all",
            "each",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
        }


def merge_keywords(all_keywords: List[List[str]], top_n: int = 30) -> List[str]:
    """合并多个关键词列表，去重并按频率排序

    Args:
        all_keywords: 多个关键词列表
        top_n: 返回前 N 个

    Returns:
        合并后的关键词列表
    """
    counter = Counter()
    for keywords in all_keywords:
        for kw in keywords:
            counter[kw.lower()] += 1

    return [kw for kw, _ in counter.most_common(top_n)]


def extract_keywords_from_documents(
    documents: List[str],
    method: str = "auto",
    sample_size: int = 10,
) -> List[str]:
    """从文档列表中提取关键词

    Args:
        documents: 文档文本列表
        method: 提取方法
        sample_size: 采样数量（避免过多 API 调用）

    Returns:
        关键词列表
    """
    extractor = KeywordExtractor()

    if len(documents) > sample_size:
        indices = set(range(0, len(documents), len(documents) // sample_size))
        documents = [documents[i] for i in indices][:sample_size]

    all_keywords = []
    for doc in documents:
        keywords = extractor.extract_from_text(doc, method=method)
        all_keywords.append(keywords)

    return merge_keywords(all_keywords)
