#!/usr/bin/env python3
"""
知识库导入工具函数

提供可复用的 ingest_one() 和 list_knowledge_bases() 函数。
CLI 入口已迁移到: python -m kb.cli
"""

from kb_core.import_service import ImportApplicationService, ImportRequest
from kb_core.registry import KnowledgeBaseRegistry, get_vault_root
from kb_core.services import KnowledgeBaseService
from rag.logger import get_logger

logger = get_logger(__name__)


def list_knowledge_bases() -> None:
    """列出所有知识库"""
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


def ingest_one(kb_id: str, rebuild: bool = False, refresh_topics: bool = True) -> bool:
    """导入单个知识库

    Args:
        kb_id: 知识库 ID
        rebuild: 是否清空后重建
        refresh_topics: 导入后是否刷新 topics

    Returns:
        bool: 是否成功
    """
    from kb_core.database import init_kb_meta_db

    registry = KnowledgeBaseRegistry()
    kb = registry.get(kb_id)
    kb_meta = init_kb_meta_db().get(kb_id)
    if kb is None and kb_meta is None:
        print(f"❌ 知识库不存在: {kb_id}")
        return False

    kb_name = kb.name if kb else kb_meta.get("name", kb_id)
    source_type = kb_meta.get("source_type", "obsidian") if kb_meta else "obsidian"
    source_paths = kb_meta.get("source_paths", []) if kb_meta else []

    print(f"\n📚 开始导入: {kb_name}")
    try:
        if source_type == "zotero":
            collection_name = source_paths[0] if source_paths else None
            req = ImportRequest(
                kind="zotero",
                kb_id=kb_id,
                async_mode=False,
                collection_name=collection_name,
                rebuild=rebuild,
                refresh_topics=refresh_topics,
            )
        elif source_type == "generic":
            paths = source_paths if source_paths else None
            req = ImportRequest(
                kind="generic",
                kb_id=kb_id,
                async_mode=False,
                paths=paths,
                rebuild=rebuild,
                refresh_topics=refresh_topics,
            )
        else:
            vault_path = str(get_vault_root())
            folder_path = source_paths[0] if source_paths else None
            req = ImportRequest(
                kind="obsidian",
                kb_id=kb_id,
                async_mode=False,
                vault_path=vault_path,
                folder_path=folder_path,
                recursive=True,
                rebuild=rebuild,
                refresh_topics=refresh_topics,
            )

        stats = ImportApplicationService.run_sync(req)
        print(
            f"✅ 完成: 文件 {stats.get('files', 0)}, 节点 {stats.get('nodes', 0)}, 失败 {stats.get('failed', 0)}"
        )
        return True
    except Exception as e:
        logger.error(f"导入失败 {kb_id}: {e}", exc_info=True)
        print(f"❌ 失败: {e}")
        return False
