#!/usr/bin/env python3
"""
LanceDB CRUD CLI 工具

用法：
    uv run python scripts/lance_crud.py <command> [args]

命令：
    list                            列出所有知识库的表
    stats <kb_id>                  查看表统计信息
    schema <kb_id>                 查看表结构
    docs <kb_id>                   查看文档摘要（按 doc_id 聚合）
    nodes <kb_id>                  查询节点
    duplicates <kb_id>              查找重复的源文件
    delete-docids <kb_id> <ids>    按 doc_id 删除（逗号分隔）
    delete-source <kb_id> <file>    按源文件删除
    delete-nodes <kb_id> <ids>     按节点 ID 删除（逗号分隔）
    export <kb_id> <output>         导出到 JSONL
    rebuild <kb_id>                重建 docstore
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import json
from typing import Optional

from kb.lance_crud import LanceCRUDService


def cmd_list():
    tables = LanceCRUDService.list_all_tables()
    print(f"{'KB ID':<30} {'名称':<20} {'表名':<25} {'行数':<12} {'大小(MB)':<10}")
    print("-" * 100)
    for t in tables:
        status = t.get("status", "ok")
        if status != "ok":
            print(
                f"{t['kb_id']:<30} {t.get('name', ''):<20} {status:<25} {'ERROR':<12}"
            )
        else:
            print(
                f"{t['kb_id']:<30} {t.get('name', ''):<20} {t.get('table_name', ''):<25} "
                f"{t.get('row_count', 0):<12,} {t.get('size_mb', 0):<10.2f}"
            )


def cmd_stats(kb_id: str, table_name: Optional[str]):
    stats = LanceCRUDService.get_table_stats(kb_id, table_name)
    print(f"知识库: {stats.kb_id}")
    print(f"表名: {stats.table_name}")
    print(f"URI: {stats.uri}")
    print(f"行数: {stats.row_count:,}")
    print(f"大小: {stats.size_mb:.2f} MB ({stats.size_gb:.3f} GB)")
    print(f"列: {', '.join(stats.columns)}")


def cmd_schema(kb_id: str, table_name: Optional[str]):
    schema = LanceCRUDService.get_schema(kb_id, table_name)
    print(f"表: {schema['table_name']}")
    print(f"行数: {schema['row_count']:,}")
    print(f"\n列结构:")
    for f in schema["fields"]:
        print(f"  - {f['name']}: {f['type']}")


def cmd_docs(kb_id: str, table_name: Optional[str], limit: int = 50):
    docs = LanceCRUDService.get_doc_summary(kb_id, table_name)
    print(f"文档总数: {len(docs)}")
    print(f"\n{'Doc ID':<38} {'节点数':<8} {'字符数':<12} {'源文件'}")
    print("-" * 100)
    for doc in docs[:limit]:
        source = doc.source_file or "(unknown)"
        if len(source) > 40:
            source = "..." + source[-37:]
        print(f"{doc.doc_id:<38} {doc.node_count:<8} {doc.total_chars:<12,} {source}")
    if len(docs) > limit:
        print(f"... 还有 {len(docs) - limit} 个文档")


def cmd_nodes(
    kb_id: str,
    table_name: Optional[str],
    doc_id: Optional[str],
    limit: int,
    offset: int,
):
    nodes = LanceCRUDService.query_nodes(kb_id, table_name, doc_id, limit, offset)
    print(f"返回 {len(nodes)} 个节点:")
    for n in nodes:
        text_preview = n.text[:80].replace("\n", " ")
        if len(n.text) > 80:
            text_preview += "..."
        print(f"\n[{n.id[:8]}] doc={n.doc_id[:8]} len={n.text_length}")
        print(f"  {text_preview}")


def cmd_duplicates(kb_id: str, table_name: Optional[str]):
    duplicates = LanceCRUDService.find_duplicate_sources(kb_id, table_name)
    print(f"发现 {len(duplicates)} 个有重复的源文件:\n")
    for source, doc_ids in sorted(
        duplicates.items(), key=lambda x: len(x[1]), reverse=True
    ):
        print(f"源文件: {source}")
        print(f"  版本数: {len(doc_ids)}")
        for doc_id in doc_ids:
            print(f"    - {doc_id}")
        print()


def cmd_delete_doc_ids(
    kb_id: str, doc_ids_str: str, table_name: Optional[str], dry_run: bool
):
    doc_ids = [d.strip() for d in doc_ids_str.split(",") if d.strip()]
    print(f"将删除 {len(doc_ids)} 个 doc_id 对应的所有节点...")
    if dry_run:
        print("DRY RUN - 不执行实际删除")
        return
    deleted = LanceCRUDService.delete_by_doc_ids(kb_id, doc_ids, table_name)
    print(f"已删除 {deleted} 个节点")


def cmd_delete_source(
    kb_id: str, source: str, table_name: Optional[str], dry_run: bool
):
    print(f"将删除源文件 '{source}' 对应的所有节点...")
    if dry_run:
        print("DRY RUN - 不执行实际删除")
        return
    deleted = LanceCRUDService.delete_by_source_file(kb_id, source, table_name)
    print(f"已删除 {deleted} 个节点")


def cmd_delete_nodes(
    kb_id: str, node_ids_str: str, table_name: Optional[str], dry_run: bool
):
    node_ids = [n.strip() for n in node_ids_str.split(",") if n.strip()]
    print(f"将删除 {len(node_ids)} 个节点...")
    if dry_run:
        print("DRY RUN - 不执行实际删除")
        return
    deleted = LanceCRUDService.delete_by_node_ids(kb_id, node_ids, table_name)
    print(f"已删除 {deleted} 个节点")


def cmd_export(kb_id: str, output_path: str, table_name: Optional[str]):
    print(f"导出 {kb_id} 到 {output_path} ...")
    count = LanceCRUDService.export_to_jsonl(kb_id, output_path, table_name)
    print(f"已导出 {count} 条记录")


def cmd_rebuild(kb_id: str):
    print(f"重建 {kb_id} 的 docstore ...")
    count = LanceCRUDService.rebuild_docstore(kb_id)
    print(f"已重建 {count} 个节点")


def main():
    parser = argparse.ArgumentParser(
        description="LanceDB CRUD 工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
    python scripts/lance_crud.py list
    python scripts/lance_crud.py stats animal-nutrition-breeding
    python scripts/lance_crud.py docs animal-nutrition-breeding --limit 20
    python scripts/lance_crud.py duplicates animal-nutrition-breeding
    python scripts/lance_crud.py delete-docids animal-nutrition-breeding "doc1,doc2" --dry-run
    python scripts/lance_crud.py export animal-nutrition-breeding /tmp/export.jsonl
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    subparsers.add_parser("list", help="列出所有知识库的表")

    p_stats = subparsers.add_parser("stats", help="查看表统计信息")
    p_stats.add_argument("kb_id", help="知识库 ID")
    p_stats.add_argument("--table", help="表名（默认为 kb_id）")

    p_schema = subparsers.add_parser("schema", help="查看表结构")
    p_schema.add_argument("kb_id", help="知识库 ID")
    p_schema.add_argument("--table", help="表名（默认为 kb_id）")

    p_docs = subparsers.add_parser("docs", help="查看文档摘要")
    p_docs.add_argument("kb_id", help="知识库 ID")
    p_docs.add_argument("--table", help="表名（默认为 kb_id）")
    p_docs.add_argument("--limit", type=int, default=50, help="限制数量")

    p_nodes = subparsers.add_parser("nodes", help="查询节点")
    p_nodes.add_argument("kb_id", help="知识库 ID")
    p_nodes.add_argument("--table", help="表名（默认为 kb_id）")
    p_nodes.add_argument("--doc-id", help="按 doc_id 过滤")
    p_nodes.add_argument("--limit", type=int, default=20, help="返回数量")
    p_nodes.add_argument("--offset", type=int, default=0, help="偏移量")

    p_dup = subparsers.add_parser("duplicates", help="查找重复的源文件")
    p_dup.add_argument("kb_id", help="知识库 ID")
    p_dup.add_argument("--table", help="表名（默认为 kb_id）")

    p_del_doc = subparsers.add_parser("delete-docids", help="按 doc_id 删除")
    p_del_doc.add_argument("kb_id", help="知识库 ID")
    p_del_doc.add_argument("doc_ids", help="逗号分隔的 doc_id 列表")
    p_del_doc.add_argument("--table", help="表名（默认为 kb_id）")
    p_del_doc.add_argument("--dry-run", action="store_true", help="仅预览不执行")

    p_del_src = subparsers.add_parser("delete-source", help="按源文件删除")
    p_del_src.add_argument("kb_id", help="知识库 ID")
    p_del_src.add_argument("source", help="源文件路径或文件名")
    p_del_src.add_argument("--table", help="表名（默认为 kb_id）")
    p_del_src.add_argument("--dry-run", action="store_true", help="仅预览不执行")

    p_del_node = subparsers.add_parser("delete-nodes", help="按节点 ID 删除")
    p_del_node.add_argument("kb_id", help="知识库 ID")
    p_del_node.add_argument("node_ids", help="逗号分隔的节点 ID 列表")
    p_del_node.add_argument("--table", help="表名（默认为 kb_id）")
    p_del_node.add_argument("--dry-run", action="store_true", help="仅预览不执行")

    p_exp = subparsers.add_parser("export", help="导出到 JSONL")
    p_exp.add_argument("kb_id", help="知识库 ID")
    p_exp.add_argument("output", help="输出文件路径")
    p_exp.add_argument("--table", help="表名（默认为 kb_id）")

    p_rebuild = subparsers.add_parser("rebuild", help="重建 docstore")
    p_rebuild.add_argument("kb_id", help="知识库 ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    table_name = getattr(args, "table", None)

    if args.command == "list":
        cmd_list()
    elif args.command == "stats":
        cmd_stats(args.kb_id, table_name)
    elif args.command == "schema":
        cmd_schema(args.kb_id, table_name)
    elif args.command == "docs":
        cmd_docs(args.kb_id, table_name, args.limit)
    elif args.command == "nodes":
        cmd_nodes(args.kb_id, table_name, args.doc_id, args.limit, args.offset)
    elif args.command == "duplicates":
        cmd_duplicates(args.kb_id, table_name)
    elif args.command == "delete-docids":
        cmd_delete_doc_ids(args.kb_id, args.doc_ids, table_name, args.dry_run)
    elif args.command == "delete-source":
        cmd_delete_source(args.kb_id, args.source, table_name, args.dry_run)
    elif args.command == "delete-nodes":
        cmd_delete_nodes(args.kb_id, args.node_ids, table_name, args.dry_run)
    elif args.command == "export":
        cmd_export(args.kb_id, args.output, table_name)
    elif args.command == "rebuild":
        cmd_rebuild(args.kb_id)
    else:
        print(f"未知命令: {args.command}")
        parser.print_help()


if __name__ == "__main__":
    main()
