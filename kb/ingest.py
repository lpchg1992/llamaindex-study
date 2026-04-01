#!/usr/bin/env python3
import argparse

from kb.import_service import ImportApplicationService, ImportRequest
from kb.registry import KnowledgeBaseRegistry, get_vault_root
from kb.services import KnowledgeBaseService
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


def list_knowledge_bases() -> None:
    registry = KnowledgeBaseRegistry()
    print("\n📚 知识库列表\n")
    print(f"{'ID':<20} {'名称':<20} {'状态':<10} {'topics':<8}")
    print("-" * 70)
    for kb in registry.list_all():
        info = KnowledgeBaseService.get_info(kb.id) or {}
        status = info.get("status", "unknown")
        topic_count = len(info.get("topics", []))
        print(f"{kb.id:<20} {kb.name:<20} {status:<10} {topic_count:<8}")
    print()


def ingest_one(kb_id: str, rebuild: bool = False) -> bool:
    registry = KnowledgeBaseRegistry()
    kb = registry.get(kb_id)
    if kb is None:
        print(f"❌ 知识库不存在: {kb_id}")
        return False

    print(f"\n📚 开始导入: {kb.name}")
    try:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="obsidian",
                kb_id=kb_id,
                async_mode=False,
                vault_path=str(get_vault_root()),
                recursive=True,
                rebuild=rebuild,
                refresh_topics=True,
            )
        )
        print(
            f"✅ 完成: 文件 {stats.get('files', 0)}, 节点 {stats.get('nodes', 0)}, 失败 {stats.get('failed', 0)}"
        )
        return True
    except Exception as e:
        logger.error(f"导入失败 {kb_id}: {e}", exc_info=True)
        print(f"❌ 失败: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库导入工具（统一链路）")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有知识库")
    parser.add_argument("--kb", "-k", type=str, help="指定知识库 ID")
    parser.add_argument("--rebuild", "-r", action="store_true", help="清空后重建")
    args = parser.parse_args()

    registry = KnowledgeBaseRegistry()
    if args.list:
        list_knowledge_bases()
        raise SystemExit(0)

    if args.kb:
        raise SystemExit(0 if ingest_one(args.kb, rebuild=args.rebuild) else 1)

    print("🚀 开始批量导入所有知识库\n")
    ok = 0
    fail = 0
    for kb in registry.list_all():
        if ingest_one(kb.id, rebuild=args.rebuild):
            ok += 1
        else:
            fail += 1
    print(f"\n🎉 导入完成: {ok} 成功, {fail} 失败")
    raise SystemExit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
