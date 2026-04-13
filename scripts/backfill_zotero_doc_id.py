#!/usr/bin/env python3
"""
**独立脚本**
检查并修复 documents 表的 zotero_doc_id 字段
"""

import re
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from kb.database import DatabaseManager


def main():
    db = DatabaseManager()
    db_path = db.db_path
    print(f"数据库路径: {db_path}")

    # 1. 检查列是否存在
    from sqlalchemy import inspect

    with db.engine.connect() as conn:
        columns = {c["name"] for c in inspect(db.engine).get_columns("documents")}

    if "zotero_doc_id" not in columns:
        print("❌ zotero_doc_id 列不存在，请先重启 api.py 以触发迁移")
        return

    print(f"✅ zotero_doc_id 列已存在")

    # 2. 检查数据统计
    with db.engine.connect() as conn:
        result = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM documents WHERE zotero_doc_id IS NOT NULL"
        )
        filled = result.fetchone()[0]

        result2 = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM documents WHERE id LIKE 'zotero_%'"
        )
        total_zotero = result2.fetchone()[0]

        result3 = conn.exec_driver_sql("SELECT COUNT(*) FROM documents")
        total = result3.fetchone()[0]

    print(f"\n文档统计:")
    print(f"  总文档数: {total}")
    print(f"  Zotero 文档数: {total_zotero}")
    print(f"  已填充 zotero_doc_id: {filled}")
    print(f"  未填充: {total_zotero - filled}")

    # 3. 回填
    if total_zotero > filled:
        print(f"\n开始回填...")
        with db.engine.connect() as conn:
            result = conn.exec_driver_sql(
                "SELECT id FROM documents WHERE zotero_doc_id IS NULL AND id LIKE 'zotero_%'"
            )
            rows = result.fetchall()

        updated = 0
        for row in rows:
            doc_id = row[0]
            m = re.match(r"^zotero_(\d+)", doc_id)
            if m:
                zotero_doc_id = f"zotero_{m.group(1)}"
                with db.engine.begin() as conn:
                    conn.exec_driver_sql(
                        "UPDATE documents SET zotero_doc_id = ? WHERE id = ?",
                        (zotero_doc_id, doc_id),
                    )
                updated += 1

        print(f"✅ 回填完成，共更新 {updated} 条记录")
    else:
        print("\n✅ 所有 Zotero 文档已填充 zotero_doc_id")

    # 4. 抽样显示
    print(f"\n抽样检查 (前 5 条 Zotero 文档):")
    with db.engine.connect() as conn:
        result = conn.exec_driver_sql(
            "SELECT id, zotero_doc_id, source_file FROM documents WHERE id LIKE 'zotero_%' LIMIT 5"
        )
        for row in result.fetchall():
            print(f"  id={row[0]}  zotero_doc_id={row[1]}  file={row[2]}")


if __name__ == "__main__":
    main()
