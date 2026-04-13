#!/usr/bin/env python3
import argparse
import sys

from kb.import_service import ImportApplicationService, ImportRequest
from kb.services import KnowledgeBaseService
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


def show_status(kb_id: str) -> int:
    info = KnowledgeBaseService.get_info(kb_id)
    if not info:
        print(f"❌ 知识库不存在: {kb_id}")
        return 1
    print(f"知识库: {kb_id}")
    print(f"状态: {info.get('status', 'unknown')}")
    print(f"向量数: {info.get('row_count', 0)}")
    print(f"topics: {len(info.get('topics', []))}")
    return 0


def run_ingest(
    kb_id: str,
    collection_id: str,
    collection_name: str,
    rebuild: bool,
    refresh_topics: bool = True,
) -> int:
    try:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="zotero",
                kb_id=kb_id,
                async_mode=False,
                collection_id=collection_id or None,
                collection_name=collection_name or None,
                rebuild=rebuild,
                refresh_topics=refresh_topics,
            )
        )
        print(
            f"✅ 完成: 文献 {stats.get('items', 0)}, 节点 {stats.get('nodes', 0)}, 失败 {stats.get('failed', 0)}"
        )
        return 0
    except Exception as e:
        logger.error(f"导入失败: {e}", exc_info=True)
        print(f"❌ 失败: {e}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Zotero 导入工具（统一链路）")
    parser.add_argument("--kb-id", required=True, help="目标知识库 ID")
    parser.add_argument("--collection-id", default="", help="Zotero 收藏夹 ID")
    parser.add_argument("--collection-name", default="", help="Zotero 收藏夹名称")
    parser.add_argument("--status", "-s", action="store_true", help="查看知识库状态")
    parser.add_argument("--rebuild", "-r", action="store_true", help="清空后重建")
    parser.add_argument(
        "--refresh-topics",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="导入完成后是否刷新 topics",
    )
    args = parser.parse_args()

    if not args.status and not args.collection_id and not args.collection_name:
        print("❌ 需要提供 --collection-id 或 --collection-name")
        raise SystemExit(1)

    if args.status:
        raise SystemExit(show_status(args.kb_id))
    raise SystemExit(
        run_ingest(
            kb_id=args.kb_id,
            collection_id=args.collection_id,
            collection_name=args.collection_name,
            rebuild=args.rebuild,
            refresh_topics=args.refresh_topics,
        )
    )


if __name__ == "__main__":
    main()
