#!/usr/bin/env python3
"""
LanceDB to SQLite Chunk Hierarchy Sync Script

从LanceDB恢复完整的父子层级关系到SQLite chunk表。

问题：
- HierarchicalNodeParser产生的nodes包含完整的relationships信息
- 但create_document()只从node.metadata读取parent_id，忽略了node.relationships
- 导致SQLite的parent_chunk_id和hierarchy_level字段为空

解决方案：
- 从LanceDB的metadata._node_content.relationships中提取父子关系
- 同步到SQLite chunk表

用法：
    python scripts/sync_lance_to_sqlite.py                    # 同步所有知识库
    python scripts/sync_lance_to_sqlite.py --kb test_kb     # 同步指定知识库
    python scripts/sync_lance_to_sqlite.py --dry-run         # 只验证不写入
    python scripts/sync_lance_to_sqlite.py --kb test_kb --force  # 强制覆盖
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 添加项目根目录到path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sync_lance")


def get_kb_persist_dir(kb_id: str) -> str:
    """获取知识库的持久化目录"""
    from rag.config import get_settings

    settings = get_settings()
    return f"{settings.persist_dir}/{kb_id}"


def connect_lance(persist_dir: str):
    """连接到LanceDB"""
    import lancedb

    db = lancedb.connect(persist_dir)
    return db


def get_lance_table_schema(table) -> Dict[str, Any]:
    """获取LanceDB表结构"""
    schema = table.schema
    fields = {}
    for field in schema:
        fields[field.name] = str(field.type)
    return fields


def iterate_lance_table(table, batch_size: int = 1000):
    """分批迭代LanceDB表"""
    total = table.count_rows()
    offset = 0
    while offset < total:
        df = table.search().offset(offset).limit(batch_size).to_pandas()
        for _, row in df.iterrows():
            yield row
        offset += batch_size


def parse_node_content(metadata: Any) -> Tuple[Optional[str], int]:
    """
    从metadata中解析parent_chunk_id

    LlamaIndex Relationship Keys:
    - '1' = SOURCE (源文档)
    - '2' = PARENT (直接父节点) - node_type=1
    - '3' = CHILD (子节点) - node_type=1
    - '4' = 远亲/祖先节点 - node_type=1
    - '5' = CHILDREN列表 (多个子节点)

    层级结构中，'2'指向直接父节点，'4'可能指向根或祖先节点。
    应该优先使用'2'作为parent_id。

    Returns:
        (parent_chunk_id, placeholder_level) - hierarchy_level需单独计算
    """
    if not metadata:
        return None, 0

    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return None, 0

    node_content_str = metadata.get("_node_content", "{}")
    if isinstance(node_content_str, str):
        try:
            node_content = json.loads(node_content_str)
        except json.JSONDecodeError:
            return None, 0
    else:
        node_content = node_content_str

    relationships = node_content.get("relationships", {})

    # 优先查找 '2' (PARENT)，这是直接父节点
    if "2" in relationships:
        rel = relationships["2"]
        if isinstance(rel, dict):
            return rel.get("node_id"), 0

    # 如果没有 '2'，尝试 '4' (可能是远亲/祖先)
    if "4" in relationships:
        rel = relationships["4"]
        if isinstance(rel, dict):
            return rel.get("node_id"), 0

    return None, 0


def calculate_hierarchy_level(
    chunk_id: str,
    parent_map: Dict[str, Optional[str]],
    cache: Dict[str, int]
) -> int:
    if chunk_id in cache:
        return cache[chunk_id]

    level = 0
    current_id = chunk_id
    visited = set()

    while level < 2:
        parent_id = parent_map.get(current_id)
        if not parent_id or current_id in visited:
            break
        visited.add(current_id)
        current_id = parent_id
        level += 1

    cache[chunk_id] = level
    return level


def get_all_kb_ids() -> List[str]:
    """获取所有知识库ID"""
    from kb_core.database import init_kb_db

    kb_db = init_kb_db()
    with kb_db.session_scope() as session:
        from kb_core.database import KnowledgeBaseModel

        kbs = session.query(KnowledgeBaseModel).all()
        return [kb.id for kb in kbs]


def sync_kb_hierarchy(
    kb_id: str,
    dry_run: bool = True,
    force: bool = False,
    batch_size: int = 100,
) -> Dict[str, Any]:
    logger.info(f"{'[DRY-RUN] ' if dry_run else ''}开始同步知识库: {kb_id}")

    stats = {
        "total": 0,
        "fixed_parent": 0,
        "fixed_level": 0,
        "unchanged": 0,
        "errors": 0,
        "skipped_lance_missing": 0,
        "skipped_no_change": 0,
    }

    persist_dir = get_kb_persist_dir(kb_id)

    if not Path(persist_dir).exists():
        logger.warning(f"LanceDB目录不存在: {persist_dir}")
        return stats

    try:
        db = connect_lance(persist_dir)
        table_names = db.table_names()

        if kb_id not in table_names:
            logger.warning(f"LanceDB中找不到表: {kb_id}")
            return stats

        table = db.open_table(kb_id)
        total_rows = table.count_rows()
        stats["total"] = total_rows

        logger.info(f"LanceDB表 {kb_id} 共有 {total_rows} 行")

        from kb_core.database import init_chunk_db
        chunk_db = init_chunk_db()

        parent_map: Dict[str, Optional[str]] = {}
        chunk_ids = []

        for row in iterate_lance_table(table, batch_size):
            chunk_id = row.get("id")
            if not chunk_id:
                continue
            chunk_ids.append(chunk_id)
            metadata = row.get("metadata", {})
            parent_id, _ = parse_node_content(metadata)
            parent_map[chunk_id] = parent_id

        logger.info(f"收集到 {len(chunk_ids)} 个chunk的父子关系")

        level_cache: Dict[str, int] = {}
        for chunk_id in chunk_ids:
            level_cache[chunk_id] = calculate_hierarchy_level(chunk_id, parent_map, level_cache)

        level_counts: Dict[int, int] = {}
        for cid in chunk_ids:
            lvl = level_cache.get(cid, 0)
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
        logger.info(f"层级分布: {level_counts}")

        processed = 0
        to_update = []

        for chunk_id in chunk_ids:
            processed += 1
            parent_id = parent_map.get(chunk_id)
            hierarchy_level = level_cache.get(chunk_id, 0)

            current = chunk_db.get(chunk_id)
            if not current:
                stats["skipped_lance_missing"] += 1
                continue

            needs_parent_update = (force or current.get("parent_chunk_id") is None) and parent_id is not None
            needs_level_update = (force or current.get("hierarchy_level") == 0) and hierarchy_level > 0

            if needs_parent_update:
                stats["fixed_parent"] += 1
                to_update.append((chunk_id, parent_id, hierarchy_level))
            elif needs_level_update:
                stats["fixed_level"] += 1
                to_update.append((chunk_id, parent_id, hierarchy_level))
            else:
                stats["skipped_no_change"] += 1

            if len(to_update) >= batch_size:
                if not dry_run:
                    _batch_update_chunks(chunk_db, to_update)
                to_update = []

            # 进度显示
            if processed % 1000 == 0 or processed == total_rows:
                logger.info(
                    f"  进度: {processed}/{total_rows} "
                    f"| 已修复parent: {stats['fixed_parent']} "
                    f"| 已修复level: {stats['fixed_level']} "
                    f"| 跳过: {stats['skipped_no_change']}"
                )

        # 处理剩余
        if to_update and not dry_run:
            _batch_update_chunks(chunk_db, to_update)

        logger.info(
            f"同步完成: {kb_id} | "
            f"总行数: {stats['total']} | "
            f"修复parent: {stats['fixed_parent']} | "
            f"修复level: {stats['fixed_level']} | "
            f"无变化: {stats['skipped_no_change']} | "
            f"错误: {stats['errors']}"
        )

    except Exception as e:
        logger.error(f"同步 {kb_id} 时出错: {e}")
        stats["errors"] += 1

    return stats


def _batch_update_chunks(chunk_db, updates: List[Tuple[str, Optional[str], int]]):
    from kb_core.database import get_db, ChunkModel

    db = get_db()
    with db.session_scope() as session:
        for chunk_id, parent_id, hierarchy_level in updates:
            try:
                session.query(ChunkModel).filter(
                    ChunkModel.id == chunk_id
                ).update(
                    {
                        "parent_chunk_id": parent_id,
                        "hierarchy_level": hierarchy_level,
                        "updated_at": time.time(),
                    }
                )
            except Exception as e:
                logger.warning(f"更新chunk {chunk_id} 失败: {e}")


def verify_sync(kb_id: str) -> Dict[str, Any]:
    from kb_core.database import get_db, ChunkModel
    from sqlalchemy import func

    db = get_db()
    with db.session_scope() as session:
        with_parent = session.query(func.count(ChunkModel.id)).filter(
            ChunkModel.kb_id == kb_id, ChunkModel.parent_chunk_id.isnot(None)
        ).scalar()
        with_level = session.query(func.count(ChunkModel.id)).filter(
            ChunkModel.kb_id == kb_id, ChunkModel.hierarchy_level > 0
        ).scalar()
        total = session.query(func.count(ChunkModel.id)).filter(
            ChunkModel.kb_id == kb_id
        ).scalar()

        return {
            "total": total,
            "with_parent": with_parent,
            "with_level": with_level,
            "parent_ratio": f"{with_parent / total * 100:.1f}%" if total > 0 else "0%",
            "level_ratio": f"{with_level / total * 100:.1f}%" if total > 0 else "0%",
        }


def main():
    parser = argparse.ArgumentParser(
        description="同步LanceDB层级关系到SQLite chunk表"
    )
    parser.add_argument(
        "--kb",
        type=str,
        help="指定知识库ID，不指定则同步所有",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证不写入",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制覆盖已有值",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="批处理大小",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="验证同步结果",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    args = parser.parse_args()

    # 设置日志级别
    logger.setLevel(getattr(logging, args.log_level))

    start_time = time.time()

    if args.kb:
        kb_ids = [args.kb]
    else:
        kb_ids = get_all_kb_ids()
        logger.info(f"找到 {len(kb_ids)} 个知识库: {kb_ids}")

    all_stats = {}
    for kb_id in kb_ids:
        logger.info("=" * 60)
        stats = sync_kb_hierarchy(
            kb_id,
            dry_run=args.dry_run,
            force=args.force,
            batch_size=args.batch_size,
        )
        all_stats[kb_id] = stats

        if args.verify:
            verify = verify_sync(kb_id)
            logger.info(f"验证结果: {verify}")

    # 汇总统计
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"同步完成，耗时: {elapsed:.1f}s")

    total_fixed = sum(s.get("fixed_parent", 0) + s.get("fixed_level", 0) for s in all_stats.values())
    total_errors = sum(s.get("errors", 0) for s in all_stats.values())

    logger.info(f"汇总: 共修复 {total_fixed} 条记录，{total_errors} 个错误")

    if args.dry_run:
        logger.info("[DRY-RUN] 模式，未实际写入数据库")
        logger.info("如需实际写入，去除 --dry-run 参数")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
