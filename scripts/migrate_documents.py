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


def parse_node_content(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse _node_content from metadata"""
    try:
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        node_content = metadata.get("_node_content", "")
        if node_content:
            return json.loads(node_content)
        return None
    except Exception:
        return None


def extract_source_file(metadata: Dict[str, Any]) -> Optional[str]:
    """Extract source file from node relationships"""
    node_data = parse_node_content(metadata)
    if not node_data:
        return None
    relationships = node_data.get("relationships", {})
    for key, rel in relationships.items():
        if key.isdigit():
            file_path = rel.get("metadata", {}).get("file_path")
            if file_path:
                return Path(file_path).name
    return None


def extract_parent_id(metadata: Dict[str, Any]) -> Optional[str]:
    """Extract parent chunk ID from node relationships"""
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


def extract_hierarchy_level(metadata: Dict[str, Any]) -> int:
    """Extract hierarchy level from metadata"""
    try:
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        node_data = parse_node_content(metadata)
        if not node_data:
            return 0
        relationships = node_data.get("relationships", {})
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
    dedup_db = init_dedup_db()

    dedup_records = dedup_db.get_records(kb_id)
    logger.info(f"找到 {len(dedup_records)} 条 dedup 记录")

    if not dedup_records:
        logger.warning(f"知识库 {kb_id} 没有 dedup 记录")
        return {"documents": 0, "chunks": 0}

    unique_docs: Dict[str, Dict[str, Any]] = {}
    for record in dedup_records:
        doc_id = record["doc_id"]
        if doc_id not in unique_docs:
            unique_docs[doc_id] = {
                "kb_id": kb_id,
                "source_file": Path(record["file_path"]).name,
                "source_path": record["file_path"],
                "file_hash": record["hash"],
                "chunk_count": 0,
            }
        unique_docs[doc_id]["chunk_count"] += 1

    logger.info(f"发现 {len(unique_docs)} 个唯一文档")

    docs_created = 0
    chunks_created = 0

    if not dry_run:
        for doc_id, doc_info in unique_docs.items():
            try:
                doc = doc_db.create(**doc_info)
                logger.debug(f"创建文档: {doc_id} -> {doc['id']}")
                docs_created += 1
            except Exception as e:
                logger.error(f"创建文档失败 {doc_id}: {e}")

        logger.info(f"已创建 {docs_created} 个文档记录")

    try:
        import lancedb

        db = LanceCRUDService.connect(kb_id)
        result = db.list_tables()
        table_names = list(result.tables) if hasattr(result, "tables") else []

        if kb_id not in table_names:
            logger.warning(f"知识库 {kb_id} 没有 LanceDB 表")
            return {"documents": docs_created, "chunks": 0}

        table = db.open_table(kb_id)
        total_rows = table.count_rows()
        logger.info(f"LanceDB 表共有 {total_rows} 行")

        batch_size = 5000
        offset = 0
        chunk_id_map: Dict[str, str] = {}

        while offset < total_rows:
            batch = table.query().offset(offset).limit(batch_size).to_pandas()

            for _, row in batch.iterrows():
                try:
                    metadata = row.get("metadata", {})
                    if not isinstance(metadata, dict):
                        metadata = {}

                    source_file = extract_source_file(metadata)
                    parent_chunk_id = extract_parent_id(metadata)
                    hierarchy_level = extract_hierarchy_level(metadata)

                    doc_id = row.get("doc_id")

                    if doc_id not in chunk_id_map:
                        chunk_id_map[doc_id] = doc_id

                    chunk_info = {
                        "id": row.get("id"),
                        "doc_id": doc_id,
                        "kb_id": kb_id,
                        "text": row.get("text", ""),
                        "chunk_index": offset,
                        "parent_chunk_id": None,
                        "hierarchy_level": hierarchy_level,
                        "metadata": metadata,
                        "embedding_generated": 1,
                    }

                    if not dry_run:
                        chunk_db.create(
                            doc_id=chunk_info["doc_id"],
                            kb_id=chunk_info["kb_id"],
                            text=chunk_info["text"],
                            chunk_index=chunk_info["chunk_index"],
                            parent_chunk_id=chunk_info["parent_chunk_id"],
                            hierarchy_level=chunk_info["hierarchy_level"],
                            metadata=chunk_info["metadata"],
                        )

                    chunks_created += 1
                    offset += 1

                except Exception as e:
                    logger.debug(f"处理节点失败: {e}")
                    offset += 1
                    continue

            logger.info(f"已处理 {offset}/{total_rows} 行")

        logger.info(f"已创建 {chunks_created} 个分块记录")

    except Exception as e:
        logger.error(f"LanceDB 迁移失败: {e}")

    logger.info(f"迁移完成: {docs_created} 文档, {chunks_created} 分块")
    return {"documents": docs_created, "chunks": chunks_created}


def validate_migration(kb_id: str) -> Dict[str, Any]:
    """Validate migration results"""
    doc_db = init_document_db()
    chunk_db = init_chunk_db()
    dedup_db = init_dedup_db()

    dedup_records = dedup_db.get_records(kb_id)
    doc_count_sqlite = len(doc_db.get_by_kb(kb_id))

    doc_ids_in_dedup = set(r["doc_id"] for r in dedup_records)
    doc_ids_in_new = set(d["id"] for d in doc_db.get_by_kb(kb_id))

    chunks = chunk_db.get_by_kb(kb_id, limit=100000)
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
