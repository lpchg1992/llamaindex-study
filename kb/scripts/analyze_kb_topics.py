#!/usr/bin/env python3
"""
分析知识库内容并提取主题词（支持去重和相似度过滤）

用法:
    python -m kb.scripts.analyze_kb_topics                    # 分析所有知识库（dry-run）
    python -m kb.scripts.analyze_kb_topics <kb_id>           # 分析指定知识库（dry-run）
    python -m kb.scripts.analyze_kb_topics <kb_id> --update  # 分析并更新到数据库
    python -m kb.scripts.analyze_kb_topics --all --update    # 分析所有并更新
    python -m kb.scripts.analyze_kb_topics <kb_id> --force   # 强制更新（忽略显著变化检查）
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from kb.database import init_kb_meta_db
from kb.topic_analyzer import (
    analyze_and_update_topics,
    get_kb_documents_for_analysis,
    TopicAnalyzer,
)
from kb.registry import registry


def get_all_kb_ids() -> list:
    kb_ids = set()
    for kb in registry.list_all():
        kb_ids.add(kb.id)
    db = init_kb_meta_db()
    for kb_meta in db.get_all():
        kb_ids.add(kb_meta["kb_id"])
    return list(kb_ids)


def analyze_kb(kb_id: str, use_llm: bool = True) -> list:
    print(f"\n分析知识库: {kb_id}")
    docs = get_kb_documents_for_analysis(kb_id, sample_size=50)
    if not docs:
        print(f"  未找到文档")
        return []
    print(f"  获取到 {len(docs)} 篇文档")
    analyzer = TopicAnalyzer()
    topics = analyzer.extract_topics(docs, use_llm=use_llm)
    print(f"  提取到 {len(topics)} 个主题词")
    return topics


def main():
    import argparse

    parser = argparse.ArgumentParser(description="分析知识库内容并提取主题词")
    parser.add_argument("kb_id", nargs="?", help="知识库 ID（省略则分析所有）")
    parser.add_argument("--all", action="store_true", help="分析所有知识库")
    parser.add_argument("--update", action="store_true", help="更新到数据库")
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help="仅显示，不更新"
    )
    parser.add_argument(
        "--force", action="store_true", help="强制更新（忽略显著变化检查）"
    )
    parser.add_argument(
        "--statistical", action="store_true", help="使用统计方法（不用LLM）"
    )

    args = parser.parse_args()

    if args.all:
        kb_ids = get_all_kb_ids()
    elif args.kb_id:
        kb_ids = [args.kb_id]
    else:
        parser.print_help()
        print("\n请指定 kb_id 或使用 --all")
        return

    print(f"将分析 {len(kb_ids)} 个知识库")

    for kb_id in kb_ids:
        topics = analyze_kb(kb_id, use_llm=not args.statistical)
        if topics:
            print(f"  主题词: {', '.join(topics[:15])}...")
            if len(topics) > 15:
                print(f"  ... 共 {len(topics)} 个")
            if args.update and not args.dry_run:
                if args.force:
                    from kb.database import init_kb_meta_db

                    db = init_kb_meta_db()
                    db.update_topics(
                        kb_id, [t[0] if isinstance(t, tuple) else t for t in topics]
                    )
                    print(f"  已强制更新到数据库")
                else:
                    result = analyze_and_update_topics(kb_id, has_new_docs=True)
                    print(f"  已处理，显著变化已更新到数据库")
        else:
            print(f"  未能提取主题词")

    print("\n完成!")


if __name__ == "__main__":
    main()
