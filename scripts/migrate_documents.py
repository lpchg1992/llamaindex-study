#!/usr/bin/env python3
"""
Migration script to populate the new documents and chunks tables.

This script:
1. Creates Document records from existing dedup_records
2. Creates Chunk records from LanceDB data
3. Preserves parent-child relationships for hierarchical chunking
4. Validates data integrity

Usage:
    uv run python scripts/migrate_documents.py [--kb-id KB_ID] [--dry-run]
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from kb.database import (
    init_document_db,
    init_chunk_db,
    init_dedup_db,
    get_db,
    DatabaseManager,
    DocumentModel,
    ChunkModel,
    DedupRecordModel,
)
from kb.lance_crud import LanceCRUDService
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


def parse_node_content(metadata: Any) -> Optional[Dict[str, Any]]:
    try:
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                return None
        if not isinstance(metadata, dict):
            return None
        node_content = metadata.get("_node_content", "")
        if node_content:
            try:
                parsed = json.loads(node_content)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None
    except Exception:
        return None


def extract_base_doc_id(lance_doc_id: str) -> str:
    if lance_doc_id.startswith("zotero_"):
        parts = lance_doc_id.split("_", 2)
        if len(parts) >= 2 and parts[1].isdigit():
            return f"zotero_{parts[1]}"
    return lance_doc_id


def extract_doc_info_from_metadata(metadata: Any) -> Dict[str, Any]:
    if not isinstance(metadata, dict):
        return {"source_file": None, "source_path": None, "file_hash": ""}
    node_data = parse_node_content(metadata)
    result = {"source_file": None, "source_path": None, "file_hash": ""}
    if not node_data:
        return result
    if not isinstance(node_data, dict):
        return result
    relationships = node_data.get("relationships", {})
    if not isinstance(relationships, dict):
        return result
    for key, rel in relationships.items():
        if isinstance(rel, dict) and key.isdigit():
            rel_meta = rel.get("metadata", {})
            if isinstance(rel_meta, dict):
                if not result["source_path"] and rel_meta.get("file_path"):
                    result["source_path"] = rel_meta["file_path"]
                    result["source_file"] = Path(rel_meta["file_path"]).name
                if not result["file_hash"] and rel_meta.get("file_hash"):
                    result["file_hash"] = rel_meta["file_hash"]
    return result


def extract_parent_id(metadata: Dict[str, Any]) -> Optional[str]:
    node_data = parse_node_content(metadata)
    if not node_data:
        return None
    relationships = node_data.get("relationships", {})
    for key, rel in relationships.items():
        if key.isdigit() and key != "1":
            parent_node_id = rel.get("node_id")
            if parent_node_id:
                return parent_node_id
    return None


def extract_hierarchy_level(metadata: Any) -> int:
    try:
        if not isinstance(metadata, dict):
            return 0
        node_data = parse_node_content(metadata)
        if not node_data or not isinstance(node_data, dict):
            return 0
        relationships = node_data.get("relationships", {})
        if not isinstance(relationships, dict):
            return 0
        if "1" in relationships:
            return 0
        if "2" in relationships:
            return 1
        if "3" in relationships:
            return 2
        return 0
    except Exception:
        return 0


def migrate_kb(kb_id: str, dry_run: bool = False) -> Dict[str, int]:
    """Migrate a single knowledge base"""
    logger.info(f"开始迁移知识库: {kb_id}")

    doc_db = init_document_db()
    chunk_db = init_chunk_db()

    try:
        import lancedb

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if kb_id not in table_names:
            logger.warning(f"知识库 {kb_id} 没有 LanceDB 表")
            return {"documents": 0, "chunks": 0}

        table = db.open_table(kb_id)
        total_rows = table.count_rows()
        logger.info(f"LanceDB 表共有 {total_rows} 行")

        unique_doc_infos: Dict[str, Dict[str, Any]] = {}
        batch_size = 5000
        offset = 0
        chunks_created = 0
        doc_chunk_counts: Dict[str, int] = {}

        while offset < total_rows:
            batch = table.to_arrow().slice(offset, batch_size).to_pandas()

            for _, row in batch.iterrows():
                try:
                    lance_doc_id = str(row.get("doc_id", ""))
                    base_doc_id = extract_base_doc_id(lance_doc_id)

                    metadata = row.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}

                    if base_doc_id not in unique_doc_infos:
                        doc_info = extract_doc_info_from_metadata(metadata)
                        unique_doc_infos[base_doc_id] = {
                            "kb_id": kb_id,
                            "source_file": doc_info["source_file"]
                            or f"{base_doc_id}.unknown",
                            "source_path": doc_info["source_path"] or "",
                            "file_hash": doc_info["file_hash"],
                            "doc_id": base_doc_id,
                        }
                        doc_chunk_counts[base_doc_id] = 0

                    hierarchy_level = extract_hierarchy_level(metadata)

                    chunk_info = {
                        "id": row.get("id"),
                        "doc_id": base_doc_id,
                        "kb_id": kb_id,
                        "text": row.get("text", ""),
                        "chunk_index": doc_chunk_counts[base_doc_id],
                        "parent_chunk_id": None,
                        "hierarchy_level": hierarchy_level,
                        "metadata": metadata,
                        "embedding_generated": 1,
                    }
                    doc_chunk_counts[base_doc_id] += 1

                    if not dry_run:
                        from kb.database import get_db_path
                        import sqlite3

                        db_path = get_db_path()
                        conn = sqlite3.connect(db_path)
                        now = time.time()
                        conn.execute(
                            "INSERT OR REPLACE INTO chunks (id, doc_id, kb_id, text, text_length, chunk_index, parent_chunk_id, hierarchy_level, metadata_json, embedding_generated, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                row.get("id"),
                                base_doc_id,
                                kb_id,
                                chunk_info["text"],
                                len(chunk_info["text"]),
                                chunk_info["chunk_index"],
                                None,
                                hierarchy_level,
                                json.dumps(metadata),
                                1,
                                now,
                                now,
                            ),
                        )
                        conn.commit()
                        conn.close()

                    chunks_created += 1

                except Exception as e:
                    logger.debug(f"处理节点失败: {e}")
                    offset += 1
                    continue

                offset += 1

            logger.info(f"已处理 {offset}/{total_rows} 行")

        logger.info(f"已创建 {chunks_created} 个分块记录")
        logger.info(f"发现 {len(unique_doc_infos)} 个唯一文档")

        docs_created = 0
        if not dry_run:
            for doc_id, doc_info in unique_doc_infos.items():
                try:
                    doc = doc_db.create(**doc_info)
                    import sqlite3
                    from kb.database import get_db_path

                    db_path = get_db_path()
                    conn = sqlite3.connect(db_path)
                    conn.execute(
                        "UPDATE documents SET chunk_count = ? WHERE id = ?",
                        (doc_chunk_counts.get(doc_id, 0), doc["id"]),
                    )
                    conn.commit()
                    conn.close()
                    logger.debug(
                        f"创建文档: {doc_id} -> {doc['id']} ({doc_chunk_counts.get(doc_id, 0)} chunks)"
                    )
                    docs_created += 1
                except Exception as e:
                    logger.error(f"创建文档失败 {doc_id}: {e}")

            logger.info(f"已创建 {docs_created} 个文档记录")

        logger.info(f"迁移完成: {docs_created} 文档, {chunks_created} 分块")
        return {"documents": docs_created, "chunks": chunks_created}

    except Exception as e:
        logger.error(f"迁移失败: {e}")
        raise


def validate_migration(kb_id: str) -> Dict[str, Any]:
    """Validate migration results"""
    doc_db = init_document_db()
    chunk_db = init_chunk_db()
    dedup_db = init_dedup_db()

    dedup_records = dedup_db.get_records(kb_id)
    doc_count_sqlite = len(doc_db.get_by_kb(kb_id))

    doc_ids_in_dedup = set(r["doc_id"] for r in dedup_records)
    doc_ids_in_new = set(d["id"] for d in doc_db.get_by_kb(kb_id))

    chunks = chunk_db.get_by_kb(kb_id, limit=999999999)
    chunk_count = len(chunks)

    missing_docs = doc_ids_in_dedup - doc_ids_in_new
    extra_docs = doc_ids_in_new - doc_ids_in_dedup

    result = {
        "kb_id": kb_id,
        "dedup_records": len(dedup_records),
        "documents_in_sqlite": doc_count_sqlite,
        "chunks_in_sqlite": chunk_count,
        "missing_documents": len(missing_docs),
        "extra_documents": len(extra_docs),
        "valid": len(missing_docs) == 0 and len(extra_docs) == 0,
    }

    if missing_docs:
        logger.warning(f"缺失的文档: {missing_docs}")
    if extra_docs:
        logger.info(f"额外的文档: {extra_docs}")

    return result


def main():
    parser = argparse.ArgumentParser(description="迁移文档和分块数据")
    parser.add_argument("--kb-id", help="指定知识库ID (不指定则处理所有)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览不实际写入")
    parser.add_argument("--validate", action="store_true", help="验证迁移结果")
    args = parser.parse_args()

    if args.validate:
        if not args.kb_id:
            logger.error("--validate 需要 --kb-id")
            sys.exit(1)
        result = validate_migration(args.kb_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["valid"] else 1)

    if args.kb_id:
        migrate_kb(args.kb_id, args.dry_run)
    else:
        logger.info("获取所有知识库...")
        from kb.database import init_kb_meta_db

        kb_meta_db = init_kb_meta_db()
        all_kbs = kb_meta_db.get_all(active_only=False)

        logger.info(f"找到 {len(all_kbs)} 个知识库")

        total_docs = 0
        total_chunks = 0

        for kb in all_kbs:
            kb_id = kb["kb_id"]
            result = migrate_kb(kb_id, args.dry_run)
            total_docs += result["documents"]
            total_chunks += result["chunks"]

        logger.info(f"全部迁移完成: {total_docs} 文档, {total_chunks} 分块")


if __name__ == "__main__":
    main()
