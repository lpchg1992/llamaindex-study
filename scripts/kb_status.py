#!/usr/bin/env python3
"""
知识库状态检查脚本

提供准确的知识库状态检查，正确处理 LanceDB 的目录结构。

LanceDB 目录结构：
- KB 根目录/        ← 直接连接此目录
    ├── _latest.manifest (如果有)
    ├── data/          (如果缺少 manifest)
    ├── _versions/
    └── _transactions/
"""

import lancedb
from pathlib import Path
from typing import Optional


def get_kb_stats(kb_path: Path, kb_id: str) -> Optional[dict]:
    """
    获取知识库统计信息
    
    Args:
        kb_path: 知识库根目录路径
        kb_id: 知识库 ID
        
    Returns:
        统计信息字典，如果失败返回 None
    """
    if not kb_path.exists():
        return None
    
    try:
        # 连接根目录（不是 *.lance 子目录）
        db = lancedb.connect(str(kb_path))
        tables = db.list_tables()
        table_list = list(tables.tables) if hasattr(tables, 'tables') else []
        
        if kb_id not in table_list:
            return {"exists": False, "row_count": 0}
        
        # 打开表
        table = db.open_table(kb_id)
        row_count = table.count_rows()
        
        # 计算大小（包括所有文件）
        total_size = 0
        file_count = 0
        for f in kb_path.rglob('*'):
            if f.is_file():
                # 排除进度文件等非数据文件
                if not f.name.startswith('.') and not f.name.endswith('.json'):
                    total_size += f.stat().st_size
                    file_count += 1
        
        return {
            "exists": True,
            "row_count": row_count,
            "size_bytes": total_size,
            "size_mb": total_size / 1024 / 1024,
            "size_gb": total_size / 1024 / 1024 / 1024,
            "file_count": file_count,
            "tables": table_list,
        }
        
    except Exception as e:
        return {"exists": False, "error": str(e)}


def check_kb(kb_path: Path, kb_id: str, name: str) -> dict:
    """检查单个知识库"""
    stats = get_kb_stats(kb_path, kb_id)
    
    if stats is None:
        return {
            "id": kb_id,
            "name": name,
            "status": "❌ 不存在",
            "row_count": "-",
            "size_mb": "-",
        }
    
    if not stats.get("exists", False):
        return {
            "id": kb_id,
            "name": name,
            "status": "⚠️ 损坏",
            "row_count": "-",
            "size_mb": "-",
            "error": stats.get("error", "未知错误"),
        }
    
    return {
        "id": kb_id,
        "name": name,
        "status": "✅ 正常",
        "row_count": f"{stats['row_count']:,}",
        "size_mb": f"{stats['size_mb']:.2f}",
    }


def main():
    print("=" * 70)
    print("📊 知识库状态检查")
    print("=" * 70)
    
    base_path = Path("/Volumes/online/llamaindex")
    
    # 定义知识库：(目录路径, 表名, 显示名称)
    # 注意：有些 KB 的表名与目录名不同
    kbs = [
        # Zotero - 表在 zotero/zotero_nutrition/ 目录下
        ("zotero/zotero_nutrition", "zotero_nutrition", "📖 Zotero 文献库"),
        
        # Hitech History - 表在 hitech_history/ 目录下
        ("hitech_history", "hitech_history", "🏢 高新历史项目库"),
        
        # Obsidian 知识库（在 obsidian/ 子目录下）
        # ("obsidian/swine_nutrition", "swine_nutrition", "🐷 猪营养技术库"),
        # ("obsidian/rd_experiments", "rd_experiments", "📊 试验研发库"),
    ]
    
    print(f"\n📁 存储根目录: {base_path}")
    print(f"   存在: {base_path.exists()}\n")
    
    print("-" * 70)
    print(f"{'ID':<25} {'名称':<20} {'状态':<12} {'向量数':<10} {'大小':<12}")
    print("-" * 70)
    
    total_vectors = 0
    total_size = 0
    
    for kb_path_suffix, kb_id, name in kbs:
        kb_path = base_path / kb_path_suffix
        result = check_kb(kb_path, kb_id, name)
        
        status = result["status"]
        row_count = result["row_count"]
        size_mb = result["size_mb"]
        
        if "✅" in status:
            total_vectors += int(row_count.replace(",", "")) if row_count != "-" else 0
            size_gb = float(size_mb) / 1024 if size_mb != "-" else 0
            total_size += size_gb
            size_str = f"{size_gb:.2f} GB"
        else:
            size_str = size_mb
        
        print(f"{kb_id:<25} {name:<20} {status:<12} {row_count:<10} {size_str:<12}")
    
    print("-" * 70)
    print(f"总计: {total_vectors:,} 向量, {total_size:.2f} GB")
    print("=" * 70)
    
    # 检查 obsidian 子目录
    obsidian_path = base_path / "obsidian"
    if obsidian_path.exists():
        subdirs = [d for d in obsidian_path.iterdir() if d.is_dir()]
        if subdirs:
            print(f"\n📁 Obsidian 子目录 ({len(subdirs)} 个):")
            for d in sorted(subdirs):
                stats = get_kb_stats(d, d.name)
                if stats and stats.get("exists"):
                    print(f"   - {d.name}: {stats['row_count']:,} 向量")
                else:
                    print(f"   - {d.name}: 空目录")


if __name__ == "__main__":
    main()
