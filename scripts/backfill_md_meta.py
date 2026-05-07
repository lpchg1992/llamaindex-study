#!/usr/bin/env python3
"""
为缺少 .meta.json 的 MD 缓存文件补充元数据。

用法:
    uv run python scripts/backfill_md_meta.py [--dry-run]
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rag.config import get_settings


def backfill_meta(mddocs_dir: Path, dry_run: bool = False) -> tuple[int, int]:
    """为缺少 meta.json 的 md 文件创建元数据。

    Returns:
        (created_count, skipped_count)
    """
    if not mddocs_dir.exists():
        print(f"mddocs 目录不存在: {mddocs_dir}")
        return 0, 0

    md_files = list(mddocs_dir.glob("*.md"))
    if not md_files:
        print(f"mddocs 目录中没有 .md 文件: {mddocs_dir}")
        return 0, 0

    created = 0
    skipped = 0

    for md_path in sorted(md_files):
        meta_path = md_path.with_suffix(".meta.json")

        if meta_path.exists():
            skipped += 1
            continue

        # 获取 md 文件的修改时间作为 converted_at
        mtime = md_path.stat().st_mtime
        converted_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

        meta = {
            "uid": None,
            "mineru_batch_id": None,
            "is_truncated": False,
            "converted_at": converted_at,
            "source_pdf": None,
            "page_count": 0,
        }

        if dry_run:
            print(f"  [DRY RUN] 将创建: {meta_path.name}")
            created += 1
        else:
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
                print(f"  ✅ 创建: {meta_path.name}")
                created += 1
            except OSError as e:
                print(f"  ❌ 失败 {meta_path.name}: {e}")

    return created, skipped


def main():
    dry_run = "--dry-run" in sys.argv

    settings = get_settings()
    mddocs_dir = Path(settings.llamaindex_storage_base) / "mddocs"

    print(f"MD 缓存目录: {mddocs_dir}")
    print(f"模式: {'预览 (不会实际写入)' if dry_run else '写入'}")
    print()

    created, skipped = backfill_meta(mddocs_dir, dry_run=dry_run)

    print()
    print(f"结果: 新建 {created} 个, 跳过 {skipped} 个 (已有 meta.json)")

    if dry_run and created > 0:
        print("\n运行 'uv run python scripts/backfill_md_meta.py' 执行实际写入。")


if __name__ == "__main__":
    main()
