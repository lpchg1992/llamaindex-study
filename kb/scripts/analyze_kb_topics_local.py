#!/usr/bin/env python3
"""
一次性脚本：使用本地模型分析已有知识库的主题词

处理流程：
1. 每个chunk → 本地模型提取主题词
2. 本地规则过滤（garbage、停用词、相似度）
3. 合并所有结果 → 本地模型二次自我审查
4. 最终结果

用法:
    python -m kb.scripts.analyze_kb_topics_local <kb_id> [--update]
"""

import sys
import re
from pathlib import Path
from collections import Counter
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

OLLAMA_URL = "http://localhost:11434/api/chat"
LOCAL_MODEL = "tomng/lfm2.5-instruct:1.2b"

EXTRACT_PROMPT = """你是一个专业的知识库主题分析助手。请从以下文档内容中提取3-8个主题词。
要求：
1. 只提取专业术语、学术名词、具体概念
2. 只提取名词性词汇，不要动词、形容词
3. 用换行符分隔，每行一个词

---文档内容---
{text}
---文档结束---

主题词（每行一个）："""

REVIEW_PROMPT = """以下是从知识库文档中提取的主题词。请审查并过滤掉：
1. 过于通用的词（如"实验设计"、"专业术语"、"使用者"、"注意事项"）
2. 疑似幻觉/错误的词（如"端生合成"）
3. 动词、形容词、副词
4. 长度小于2的词

保留真正有学科特色的专业术语。

主题词列表：
{keywords}

过滤后的有效主题词（每行一个，只返回有效的）："""


def extract_topics_from_text(text: str) -> List[str]:
    import httpx

    prompt = EXTRACT_PROMPT.format(text=text[:2000])
    try:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": LOCAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("message", {}).get("content", "")
        keywords = []
        for line in result.split("\n"):
            line = line.strip().strip("0123456789.-、，、:：) ")
            if line and len(line) >= 2:
                keywords.append(line)
        return keywords
    except Exception as e:
        print(f"  [警告] 提取失败: {e}")
        return []


def review_keywords(keywords: List[str]) -> List[str]:
    import httpx

    if not keywords:
        return []
    keywords_str = "\n".join(keywords)
    prompt = REVIEW_PROMPT.format(keywords=keywords_str)
    try:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": LOCAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("message", {}).get("content", "")
        reviewed = []
        for line in result.split("\n"):
            line = line.strip().strip("0123456789.-、，、:：) ")
            if line and len(line) >= 2:
                reviewed.append(line)
        return reviewed
    except Exception as e:
        print(f"  [警告] 审查失败: {e}")
        return keywords


def _is_garbage(kw: str) -> bool:
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
        "实验设计",
        "专业术语",
        "使用者",
        "注意事项",
    }
    if kw.lower() in junk:
        return True
    if re.match(r"^\d+$", kw):
        return True
    if re.match(r"^[a-zA-Z]{1,2}$", kw):
        return True
    return False


def _is_similar(kw1: str, kw2: str) -> bool:
    if kw1.lower() == kw2.lower():
        return True
    particles = {"的", "之", "于", "在", "和", "与", "及"}
    rp1 = "".join(c for c in kw1 if c not in particles)
    rp2 = "".join(c for c in kw2 if c not in particles)
    if rp1 and rp2:
        if rp1 in rp2 or rp2 in rp1:
            return True
    n = 2
    ngrams1 = (
        set(kw1[i : i + n] for i in range(len(kw1) - n + 1)) if len(kw1) >= n else {kw1}
    )
    ngrams2 = (
        set(kw2[i : i + n] for i in range(len(kw2) - n + 1)) if len(kw2) >= n else {kw2}
    )
    if not ngrams1 or not ngrams2:
        return False
    intersection = len(ngrams1 & ngrams2)
    union = len(ngrams1 | ngrams2)
    return (intersection / union) >= 0.75 if union > 0 else False


def local_rule_filter(keywords: List[str]) -> List[str]:
    result = []
    for kw in keywords:
        if _is_garbage(kw):
            continue
        is_dup = False
        for existing in result:
            if _is_similar(kw, existing):
                is_dup = True
                break
        if not is_dup:
            result.append(kw)
    return result


def merge_and_deduplicate(keywords_list: List[List[str]]) -> List[str]:
    counter = Counter()
    for keywords in keywords_list:
        for kw in keywords:
            if _is_garbage(kw):
                continue
            counter[kw] += 1
    merged = [kw for kw, _ in counter.most_common(80)]
    return local_rule_filter(merged)


def get_kb_chunks(kb_id: str) -> List[str]:
    from kb.registry import registry

    kb = registry.get(kb_id)
    if not kb:
        print(f"知识库不存在: {kb_id}")
        return []
    persist_dir = kb.persist_dir
    if not persist_dir.exists():
        print(f"存储目录不存在: {persist_dir}")
        return []
    try:
        import lancedb

        db = lancedb.connect(str(persist_dir))
        table_names = db.table_names()
        if not table_names:
            return []
        table = db.open_table(table_names[0])
        df = table.to_pandas()
        if "text" not in df.columns:
            return []
        return df["text"].dropna().tolist()
    except Exception as e:
        print(f"读取失败: {e}")
        return []


def get_all_kb_ids() -> List[str]:
    from kb.registry import registry

    return [kb.id for kb in registry.list_all()]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="使用本地模型分析知识库主题词")
    parser.add_argument("kb_id", nargs="?", help="知识库 ID")
    parser.add_argument("--all", action="store_true", help="处理所有知识库")
    parser.add_argument("--update", action="store_true", help="更新到数据库")
    args = parser.parse_args()

    if args.all:
        kb_ids = get_all_kb_ids()
    elif args.kb_id:
        kb_ids = [args.kb_id]
    else:
        parser.print_help()
        print("\n请指定 kb_id 或使用 --all")
        return

    for kb_id in kb_ids:
        print(f"\n{'=' * 50}")
        print(f"处理知识库: {kb_id}")
        chunks = get_kb_chunks(kb_id)
        if not chunks:
            print(f"  无文档")
            continue
        print(f"  共 {len(chunks)} 个 chunks（全部处理）")

        print(f"  [阶段1] 提取主题词...")
        all_keywords = []
        for i, chunk in enumerate(chunks):
            if len(chunk) < 50:
                continue
            keywords = extract_topics_from_text(chunk)
            if keywords:
                all_keywords.append(keywords)
            if (i + 1) % 50 == 0:
                print(f"    已处理 {i + 1}/{len(chunks)}")

        if not all_keywords:
            print(f"  未能提取主题词")
            continue

        print(f"  [阶段2] 本地规则过滤...")
        filtered = merge_and_deduplicate(all_keywords)
        print(f"  规则过滤后: {len(filtered)} 个")

        print(f"  [阶段3] 本地模型二次审查...")
        reviewed = review_keywords(filtered)
        if reviewed:
            filtered = reviewed
            print(f"  审查后: {len(filtered)} 个")
        else:
            print(f"  审查失败，保留原结果")

        print(f"\n  最终主题词 ({len(filtered)} 个):")
        for kw in filtered[:20]:
            print(f"    - {kw}")
        if len(filtered) > 20:
            print(f"    ... 共 {len(filtered)} 个")

        if args.update:
            from kb.database import init_kb_meta_db

            db = init_kb_meta_db()
            db.update_topics(kb_id, filtered)
            print(f"\n  已更新到数据库")

    print(f"\n{'=' * 50}")
    print("完成!")


if __name__ == "__main__":
    main()
