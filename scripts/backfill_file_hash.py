#!/usr/bin/env python3
"""
**独立脚本**
根据 source_path 重新计算并填充 documents 表的 file_hash"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kb.database import DatabaseManager
from kb.document_processor import DocumentProcessor


def main():
    processor = DocumentProcessor()
    db = DatabaseManager()

    with db.engine.begin() as conn:
        result = conn.exec_driver_sql(
            "SELECT id, source_path, file_hash FROM documents WHERE file_hash IS NULL OR file_hash = ''"
        )
        rows = result.fetchall()

    print(f"需要回填 file_hash 的文档: {len(rows)}")

    updated = 0
    missing = []
    for row in rows:
        doc_id, source_path, old_hash = row
        path = Path(source_path)
        if path.exists() and path.is_file():
            new_hash = processor.compute_file_hash(str(path))
            with db.engine.begin() as conn:
                conn.exec_driver_sql(
                    "UPDATE documents SET file_hash = ? WHERE id = ?",
                    (new_hash, doc_id),
                )
            updated += 1
        else:
            missing.append((doc_id, source_path))

    print(f"✅ 成功更新: {updated} 篇")
    if missing:
        print(f"❌ 文件不存在 ({len(missing)} 篇):")
        for doc_id, sp in missing[:5]:
            print(f"   {sp[:60]}...")

    if updated > 0:
        with db.engine.connect() as conn:
            result = conn.exec_driver_sql(
                "SELECT COUNT(*) FROM documents WHERE file_hash IS NOT NULL AND file_hash != ''"
            )
            filled = result.fetchone()[0]
            print(f"📊 共有 {filled} 篇文档已填充 file_hash")


if __name__ == "__main__":
    main()
