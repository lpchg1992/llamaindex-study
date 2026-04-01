"""
Topic 分析服务 - 在文档导入时动态分析和更新知识库的 topics。
"""

import re
from collections import Counter, defaultdict
from math import log
from typing import Dict, List, Set, Tuple

from llamaindex_study.config import get_settings
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class TopicAnalyzer:
    MAX_TOPICS = 30
    TOPIC_THRESHOLD = 0.3
    SAMPLE_SIZE = 50

    def __init__(self, min_freq: int = 2):
        self.min_freq = min_freq

    def extract_topics(
        self, documents: List[str], use_llm: bool = True
    ) -> List[Tuple[str, float]]:
        if not documents:
            return []
        if use_llm:
            llm_topics = self._llm_extract_topics(documents)
            if llm_topics:
                return llm_topics
        return self._stat_extract_topics(documents)

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"!\[\[.*?\]\]", "", text)
        text = re.sub(r"\[\[.*?\|.*?\]\]", "", text)
        text = re.sub(r"#+\s+", "", text)
        text = re.sub(r"\*\*+", "", text)
        text = re.sub(r"http\S+", "", text)
        text = re.sub(r"\[\d+\]", "", text)
        text = re.sub(r"---+", " ", text)
        text = re.sub(r"\n{3,}", " ", text)
        return text.strip()

    def _llm_extract_topics(self, texts: List[str]) -> List[Tuple[str, float]]:
        try:
            import httpx

            settings = get_settings()

            combined_text = "\n---\n".join(texts[:30])
            if len(combined_text) > 8000:
                combined_text = combined_text[:8000]

            prompt = (
                "你是一个专业的知识库主题分析助手。请从以下文档内容中提取15-25个主题词。\n"
                "要求：\n"
                "1. 只提取专业术语、学术名词、具体概念（如蛋白质代谢、猪营养配方、线性规划等）\n"
                "2. 只提取名词性词汇，不要动词、形容词、副词、介词\n"
                "3. 优先提取能体现学科领域特色的专业词汇\n"
                "4. 用换行符分隔，每行一个词\n\n"
                "---文档内容---\n"
                f"{combined_text}\n"
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
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()

            keywords = []
            seen = set()
            for line in result.split("\n"):
                line = line.strip().strip("0123456789.-、，、:：) ")
                if (
                    line
                    and len(line) >= 2
                    and not self._is_garbage(line)
                    and line.lower() not in self._get_stopwords()
                ):
                    if line.lower() not in seen:
                        keywords.append(line)
                        seen.add(line.lower())

            return [(k, 0.8) for k in keywords[:30]]

        except Exception as e:
            logger.warning(f"LLM topic 提取失败: {e}")
            return []

    def _tokenize_text(self, text: str) -> List[str]:
        cleaned = self._clean_text(text)
        pattern = r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{2,}"
        tokens = re.findall(pattern, cleaned)
        normalized: List[str] = []
        stopwords = self._get_stopwords()
        for token in tokens:
            token = token.strip()
            if re.match(r"^[A-Za-z]", token):
                token = token.lower()
            if token.lower() in stopwords:
                continue
            if self._is_garbage(token):
                continue
            normalized.append(token)
        return normalized

    def _stat_extract_topics(self, texts: List[str]) -> List[Tuple[str, float]]:
        if not texts:
            return []

        tf_counter = Counter()
        doc_counter = Counter()
        doc_count = len(texts)

        for text in texts:
            tokens = self._tokenize_text(text)
            if not tokens:
                continue
            tf_counter.update(tokens)
            doc_counter.update(set(tokens))

        if not tf_counter:
            return []

        scored: List[Tuple[str, float]] = []
        for token, tf in tf_counter.items():
            if tf < self.min_freq:
                continue
            df = doc_counter.get(token, 1)
            idf = 1.0 + log((doc_count + 1) / (df + 1))
            score = float(tf) * idf
            scored.append((token, score))

        if not scored:
            scored = [(token, float(tf)) for token, tf in tf_counter.most_common(self.MAX_TOPICS * 2)]

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: self.MAX_TOPICS]

    def _get_stopwords(self) -> Set[str]:
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
            "被",
            "把",
            "让",
            "给",
            "但",
            "却",
            "只",
            "还",
            "又",
            "从",
            "以",
            "及",
            "或",
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
            "can",
            "and",
            "but",
            "or",
            "not",
            "this",
            "that",
            "these",
            "those",
        }

    def _is_garbage(self, kw: str) -> bool:
        if not kw or len(kw) < 2:
            return True
        junk = {
            "iss",
            "thr",
            "com",
            "www",
            "http",
            "https",
            "ftp",
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "has",
            "his",
            "how",
            "its",
            "may",
            "new",
            "now",
            "old",
            "see",
            "two",
            "way",
            "who",
            "boy",
            "did",
            "get",
            "let",
            "put",
            "say",
            "she",
            "too",
            "use",
            "dir",
            "lst",
            "idx",
            "tmp",
            "bak",
            "ddd",
            "mmm",
            "yyy",
            "xxx",
            "www",
            "png",
            "jpg",
            "gif",
            "css",
            "js",
            "html",
            "xml",
            "json",
        }
        if kw.lower() in junk:
            return True
        if re.match(r"^\d+$", kw):
            return True
        if re.match(r"^[a-zA-Z]{1,2}$", kw):
            return True
        if kw in {"/", "\\", "..", "./", ".js", ".css", ".py", ".md", ".txt"}:
            return True
        return False

    def _keyword_similarity(self, kw1: str, kw2: str) -> float:
        if kw1.lower() == kw2.lower():
            return 1.0
        if kw1 in kw2 or kw2 in kw1:
            return 0.9
        particles = {"的", "之", "于", "在", "和", "与", "及", "而", "为", "之"}

        def remove_particles(s):
            return "".join(c for c in s if c not in particles)

        rp1, rp2 = remove_particles(kw1), remove_particles(kw2)
        if rp1 and rp2:
            if rp1 in rp2 or rp2 in rp1:
                return 0.85
        n = 2
        ngrams1 = (
            set(kw1[i : i + n] for i in range(len(kw1) - n + 1))
            if len(kw1) >= n
            else {kw1}
        )
        ngrams2 = (
            set(kw2[i : i + n] for i in range(len(kw2) - n + 1))
            if len(kw2) >= n
            else {kw2}
        )
        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)
        return intersection / union if union > 0 else 0.0

    def _is_similar_to_existing(
        self, keyword: str, existing: List[str], threshold: float = 0.75
    ) -> bool:
        for ex in existing:
            if self._keyword_similarity(keyword.lower(), ex.lower()) >= threshold:
                return True
        return False

    def merge_topics(
        self,
        existing: List[str],
        new_topics: List[Tuple[str, float]],
        merge_weight: float = 0.7,
    ) -> List[str]:
        if not existing and not new_topics:
            return []

        if not existing:
            return [
                topic
                for topic, _ in new_topics[: self.MAX_TOPICS]
                if not self._is_garbage(topic)
            ]

        if not new_topics:
            return [t for t in existing[: self.MAX_TOPICS] if not self._is_garbage(t)]

        existing_set = {t.lower() for t in existing}
        merged: Dict[str, float] = {}

        similar_existing = {}
        for topic, score in new_topics:
            topic_lower = topic.lower()
            if topic_lower in existing_set:
                merged[topic] = score * merge_weight + 0.3
            elif self._is_similar_to_existing(topic, existing):
                for ex in existing:
                    if self._keyword_similarity(topic.lower(), ex.lower()) >= 0.75:
                        similar_existing[ex.lower()] = ex
                        break
            else:
                merged[topic] = score

        existing_lc = {t.lower(): t for t in existing}
        for topic in existing:
            topic_lower = topic.lower()
            if topic_lower not in merged:
                if topic_lower in similar_existing:
                    merged[topic] = 0.5
                else:
                    merged[topic] = 0.2 * merge_weight

        sorted_topics = sorted(merged.items(), key=lambda x: x[1], reverse=True)
        return [
            t[0]
            for t in sorted_topics[: self.MAX_TOPICS]
            if t[1] >= self.TOPIC_THRESHOLD * 0.5 and not self._is_garbage(t[0])
        ]


def get_kb_documents_for_analysis(kb_id: str, sample_size: int = 50) -> List[str]:
    try:
        from kb.registry import registry
        from kb.database import init_kb_meta_db
        from kb.registry import get_storage_root

        kb = registry.get(kb_id)
        persist_dir = None
        if kb:
            persist_dir = kb.persist_dir
        else:
            kb_meta = init_kb_meta_db().get(kb_id)
            if kb_meta:
                persist_path = kb_meta.get("persist_path")
                if persist_path:
                    from pathlib import Path

                    persist_dir = Path(persist_path)
                else:
                    persist_dir = get_storage_root() / kb_id

        if persist_dir is None:
            return []

        if not persist_dir.exists():
            return []

        import lancedb

        db = lancedb.connect(str(persist_dir))
        table_names = db.table_names()
        if not table_names:
            return []

        table_name = kb_id if kb_id in table_names else table_names[0]
        table = db.open_table(table_name)
        df = table.to_pandas()

        if "text" not in df.columns:
            return []

        texts = df["text"].dropna().tolist()
        if len(texts) > sample_size:
            indices = list(range(0, len(texts), len(texts) // sample_size))
            texts = [texts[i] for i in indices][:sample_size]

        return texts

    except Exception as e:
        logger.warning(f"获取 KB 文档失败 {kb_id}: {e}")
        return []


def analyze_and_update_topics(
    kb_id: str, merge_weight: float = 0.7, has_new_docs: bool = True
) -> List[str]:
    from kb.database import init_kb_meta_db

    db = init_kb_meta_db()
    existing_topics = db.get_topics(kb_id)

    if has_new_docs:
        docs = get_kb_documents_for_analysis(
            kb_id, sample_size=TopicAnalyzer.SAMPLE_SIZE
        )
        if not docs:
            return existing_topics

        analyzer = TopicAnalyzer()
        new_topics = analyzer.extract_topics(docs, use_llm=True)

        merged = analyzer.merge_topics(existing_topics, new_topics, merge_weight)
    else:
        merged = existing_topics

    if merged and _is_significant_change(existing_topics, merged):
        db.update_topics(kb_id, merged)
        logger.info(f"更新 {kb_id} topics: {len(merged)} 个 (显著变化)")

    return merged if merged else existing_topics


def _is_significant_change(
    old: List[str], new: List[str], threshold: float = 0.7
) -> bool:
    if not old:
        return bool(new)
    old_set = set(t.lower() for t in old)
    new_set = set(t.lower() for t in new)
    if old_set == new_set:
        return False
    intersection = len(old_set & new_set)
    union = len(old_set | new_set)
    jaccard = intersection / union if union > 0 else 0
    return jaccard < threshold
