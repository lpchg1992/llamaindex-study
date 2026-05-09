"""
清理 LanceDB 中的孤儿向量记录。

孤儿向量：LanceDB 中存在，但 SQLite chunks 表中没有对应 chunk_id 的记录。

用法:
  python scripts/cleanup_lance_orphans.py <kb_id>          # 清理指定 KB
  python scripts/cleanup_lance_orphans.py <kb_id> --dry-run  # 仅检查，不删除
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _get_logger():
    from rag.logger import get_logger
    return get_logger(__name__)


def get_sqlite_chunk_ids(kb_id: str) -> set:
    from kb_core.database import init_chunk_db, ChunkModel
    from sqlalchemy import select

    logger = _get_logger()
    chunk_db = init_chunk_db()
    ids = set()
    try:
        with chunk_db.db.session_scope() as session:
            rows = session.scalars(
                select(ChunkModel.id).where(ChunkModel.kb_id == kb_id)
            ).all()
            ids = set(rows)
    except Exception as e:
        logger.error(f"读取 SQLite chunks 失败 {kb_id}: {e}")
    return ids


def _open_lance_table(kb_id: str):
    from kb_core.services.vector_store import VectorStoreService
    import lancedb

    vs = VectorStoreService.get_vector_store(kb_id)
    if not vs.exists():
        return None
    db = lancedb.connect(vs._get_uri())
    return db.open_table(vs.table_name)


def get_lancedb_node_ids(kb_id: str) -> set:
    logger = _get_logger()
    try:
        table = _open_lance_table(kb_id)
        if table is None:
            logger.warning(f"LanceDB 表不存在: {kb_id}")
            return set()

        ids = set()
        batch_size = 5000
        total = table.count_rows() if hasattr(table, "count_rows") else 0

        for offset in range(0, max(total, 1), batch_size):
            df = table.to_arrow().select(["id"]).slice(offset, batch_size).to_pandas()
            ids.update(df["id"].tolist())

        return ids
    except Exception as e:
        logger.error(f"读取 LanceDB 失败 {kb_id}: {e}")
        return set()


def cleanup_kb(kb_id: str, dry_run: bool = False) -> dict:
    logger = _get_logger()
    result = {
        "kb_id": kb_id,
        "sqlite_chunks": 0,
        "lance_records": 0,
        "orphan_count": 0,
        "deleted": 0,
        "dry_run": dry_run,
    }

    sqlite_ids = get_sqlite_chunk_ids(kb_id)
    lance_ids = get_lancedb_node_ids(kb_id)

    result["sqlite_chunks"] = len(sqlite_ids)
    result["lance_records"] = len(lance_ids)

    orphans = lance_ids - sqlite_ids
    result["orphan_count"] = len(orphans)

    if not orphans:
        logger.info(f"[{kb_id}] 无孤儿记录 (SQLite: {len(sqlite_ids)}, LanceDB: {len(lance_ids)})")
        return result

    logger.info(
        f"[{kb_id}] 发现 {len(orphans)} 个孤儿记录 "
        f"(SQLite: {len(sqlite_ids)}, LanceDB: {len(lance_ids)})"
    )

    orphan_doc_ids = set()
    try:
        table = _open_lance_table(kb_id)

        orphan_list = list(orphans)
        for i in range(0, len(orphan_list), 1000):
            batch = orphan_list[i : i + 1000]
            id_list = " OR ".join(f"id = '{nid}'" for nid in batch)
            df = table.to_arrow().filter(id_list).select(["id", "doc_id"]).to_pandas()
            orphan_doc_ids.update(df["doc_id"].dropna().unique().tolist())
    except Exception as e:
        logger.warning(f"读取孤儿 doc_id 失败: {e}")

    logger.info(f"  孤儿涉及 {len(orphan_doc_ids)} 个 doc_id")

    if dry_run:
        logger.info(f"  [DRY RUN] 将删除 {len(orphans)} 条 LanceDB 记录，跳过。")
        return result

    deleted = 0
    orphan_list = list(orphans)
    batch_size = 500
    try:
        table = _open_lance_table(kb_id)

        for i in range(0, len(orphan_list), batch_size):
            batch = orphan_list[i : i + batch_size]
            id_condition = " OR ".join(f"id = '{nid}'" for nid in batch)
            del_result = table.delete(id_condition)
            batch_deleted = getattr(del_result, "num_deleted", 0) or len(batch)
            deleted += batch_deleted

        logger.info(f"  [OK] 已删除 {deleted} 条孤儿记录")
    except Exception as e:
        logger.error(f"  [FAIL] 删除失败: {e}")

    result["deleted"] = deleted
    return result


def main():
    parser = argparse.ArgumentParser(description="清理 LanceDB 孤儿向量")
    parser.add_argument("kb_id", help="知识库 ID")
    parser.add_argument("--dry-run", action="store_true", help="仅检查，不删除")
    args = parser.parse_args()

    result = cleanup_kb(args.kb_id, dry_run=args.dry_run)
    print(
        f"\n[{args.kb_id}] "
        f"SQLite chunks: {result['sqlite_chunks']}, "
        f"LanceDB records: {result['lance_records']}, "
        f"孤儿: {result['orphan_count']}, "
        f"已删除: {result['deleted']}"
    )
    if args.dry_run:
        print("  (DRY RUN — 未实际删除)")


if __name__ == "__main__":
    main()
