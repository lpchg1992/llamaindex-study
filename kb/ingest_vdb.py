import argparse
from pathlib import Path
from typing import Optional
import sys

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="知识库导入任务 CLI")
    parser.add_argument("--list", action="store_true", help="列出所有知识库")
    parser.add_argument("--tasks", action="store_true", help="列出最近任务")
    parser.add_argument("--show-changes", action="store_true", help="查看待同步变更")
    parser.add_argument("--kb", help="指定知识库 ID")
    parser.add_argument(
        "--rebuild", action="store_true", help="重建知识库（清空后重新导入）"
    )
    parser.add_argument(
        "--force-delete", action="store_true", help="同步时处理已删除文件"
    )
    parser.add_argument("--limit", type=int, default=20, help="列表展示数量")
    return parser


def _print_kbs() -> int:
    from kb.registry import KnowledgeBaseRegistry

    registry = KnowledgeBaseRegistry()
    for kb in registry.list_all():
        print(f"{kb.id}\t{kb.name}\t{kb.description}")
    return 0


def _print_tasks(limit: int) -> int:
    from kb.task_queue import TaskQueue

    queue = TaskQueue()
    for task in queue.list_tasks(limit=limit):
        print(
            f"{task.task_id}\t{task.status}\t{task.task_type}\t{task.kb_id}\t{task.message}"
        )
    return 0


def _collect_markdown_files(kb, vault_root: Path) -> list[Path]:
    files: list[Path] = []
    for source_path in kb.source_paths_abs(vault_root):
        if source_path.exists():
            files.extend(source_path.rglob("*.md"))
    return files


def _show_changes(kb_id: Optional[str]) -> int:
    from kb.deduplication import DeduplicationManager
    from kb.registry import KnowledgeBaseRegistry, get_vault_root

    registry = KnowledgeBaseRegistry()
    vault_root = get_vault_root()

    targets = [registry.get(kb_id)] if kb_id else registry.list_all()
    targets = [kb for kb in targets if kb is not None]
    if not targets:
        print("未找到知识库")
        return 1

    for kb in targets:
        files = _collect_markdown_files(kb, vault_root)
        dedup_manager = DeduplicationManager(kb.id, kb.persist_dir)
        to_add, to_update, to_delete, unchanged = dedup_manager.detect_changes(
            files, vault_root
        )
        print(
            f"{kb.id}\t新增:{len(to_add)}\t更新:{len(to_update)}\t删除:{len(to_delete)}\t未变更:{len(unchanged)}"
        )
    return 0


def _submit_tasks(kb_id: Optional[str], rebuild: bool, force_delete: bool) -> int:
    from kb.registry import KnowledgeBaseRegistry
    from kb.import_service import ImportApplicationService, ImportRequest

    registry = KnowledgeBaseRegistry()
    targets = [registry.get(kb_id)] if kb_id else registry.list_all()
    targets = [kb for kb in targets if kb is not None]
    if not targets:
        print("未找到可提交的知识库")
        return 1

    for kb in targets:
        submission = ImportApplicationService.submit_task(
            ImportRequest(
                kind="obsidian",
                kb_id=kb.id,
                rebuild=rebuild,
                force_delete=force_delete,
                source="cli",
            )
        )
        print(f"{kb.id}\t{submission['task_id']}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()

    if args.list:
        return _print_kbs()
    if args.tasks:
        return _print_tasks(args.limit)
    if args.show_changes:
        return _show_changes(args.kb)
    return _submit_tasks(args.kb, args.rebuild, args.force_delete)


if __name__ == "__main__":
    raise SystemExit(main())
