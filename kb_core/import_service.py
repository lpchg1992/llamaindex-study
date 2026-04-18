from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from kb_core.services import GenericService, ObsidianService, TaskService, ZoteroService


@dataclass
class ImportRequest:
    kind: str
    kb_id: str
    async_mode: bool = True
    refresh_topics: bool = False
    source: str = ""
    path: Optional[str] = None
    paths: Optional[List[str]] = None
    include_exts: Optional[List[str]] = None
    exclude_exts: Optional[List[str]] = None
    vault_path: Optional[str] = None
    folder_path: Optional[str] = None
    recursive: bool = True
    force_delete: Optional[bool] = None
    exclude_patterns: Optional[List[str]] = None
    persist_dir: Optional[str] = None
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None
    rebuild: bool = False
    chunk_strategy: Optional[str] = None
    chunk_size: Optional[int] = None
    hierarchical_chunk_sizes: Optional[List[int]] = None


@dataclass
class SelectiveImportItem:
    type: str
    id: Optional[str] = None
    path: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


@dataclass
class SelectiveImportRequest:
    source_type: str
    items: List[SelectiveImportItem]
    async_mode: bool = True
    refresh_topics: bool = False
    prefix: str = "[kb]"


class ImportApplicationService:
    """Unified entry point for all import operations (file, Obsidian, Zotero).

    Routes requests to the appropriate service based on `kind` field,
    supporting both async (task queue) and sync (blocking) execution modes.
    """

    @staticmethod
    def execute(req: ImportRequest) -> Dict[str, Any]:
        """Execute an import request in the requested mode.

        Args:
            req: Import request with kind, kb_id, and source-specific params

        Returns:
            Task submission dict (async) or import stats dict (sync)
        """
        if req.async_mode:
            return ImportApplicationService.submit_task(req)
        return ImportApplicationService.run_sync(req)

    @staticmethod
    def submit_task(req: ImportRequest) -> Dict[str, Any]:
        if req.kind == "generic":
            params: Dict[str, Any] = {"refresh_topics": req.refresh_topics}
            if req.paths:
                params["paths"] = req.paths
            elif req.path:
                params["path"] = req.path
            if req.include_exts:
                params["include_exts"] = req.include_exts
            if req.exclude_exts:
                params["exclude_exts"] = req.exclude_exts
            if req.chunk_strategy:
                params["chunk_strategy"] = req.chunk_strategy
            if req.chunk_size:
                params["chunk_size"] = req.chunk_size
            if req.hierarchical_chunk_sizes:
                params["hierarchical_chunk_sizes"] = req.hierarchical_chunk_sizes
            source = req.source or (
                req.paths[0] if req.paths else (req.path or "generic")
            )
            return TaskService.submit(
                task_type="generic",
                kb_id=req.kb_id,
                params=params,
                source=source,
            )

        if req.kind == "obsidian":
            params = {
                "vault_path": req.vault_path,
                "folder_path": req.folder_path,
                "recursive": req.recursive,
                "force_delete": req.force_delete,
                "exclude_patterns": req.exclude_patterns,
                "rebuild": req.rebuild,
                "persist_dir": req.persist_dir,
                "refresh_topics": req.refresh_topics,
            }
            if req.chunk_strategy:
                params["chunk_strategy"] = req.chunk_strategy
            if req.chunk_size:
                params["chunk_size"] = req.chunk_size
            if req.hierarchical_chunk_sizes:
                params["hierarchical_chunk_sizes"] = req.hierarchical_chunk_sizes
            source = req.source or (req.folder_path or req.vault_path or "obsidian")
            return TaskService.submit(
                task_type="obsidian",
                kb_id=req.kb_id,
                params=params,
                source=source,
            )

        if req.kind == "zotero":
            params = {
                "collection_id": req.collection_id,
                "collection_name": req.collection_name,
                "rebuild": req.rebuild,
                "refresh_topics": req.refresh_topics,
            }
            if req.chunk_strategy:
                params["chunk_strategy"] = req.chunk_strategy
            if req.chunk_size:
                params["chunk_size"] = req.chunk_size
            if req.hierarchical_chunk_sizes:
                params["hierarchical_chunk_sizes"] = req.hierarchical_chunk_sizes
            source = req.source or (
                req.collection_name or req.collection_id or "zotero"
            )
            return TaskService.submit(
                task_type="zotero",
                kb_id=req.kb_id,
                params=params,
                source=source,
            )

        raise ValueError(f"不支持的导入类型: {req.kind}")

    @staticmethod
    def submit_selective_import(
        kb_id: str,
        req: SelectiveImportRequest,
    ) -> Dict[str, Any]:
        """Submit a selective import task for specific items (files or Zotero entries).

        Args:
            kb_id: Target knowledge base ID
            req: Selective import request with item list

        Returns:
            Task submission dict
        """
        params = {
            "items": [
                {
                    "type": item.type,
                    "id": item.id,
                    "path": item.path,
                    "options": item.options or {},
                }
                for item in req.items
            ],
            "async_mode": req.async_mode,
            "refresh_topics": req.refresh_topics,
            "prefix": req.prefix,
        }
        source = f"selective:{req.source_type}:{len(req.items)}items"
        return TaskService.submit(
            task_type="selective",
            kb_id=kb_id,
            params=params,
            source=source,
        )

    @staticmethod
    def run_sync(req: ImportRequest) -> Dict[str, Any]:
        """Execute an import request synchronously (blocking).

        Directly calls the appropriate service method without going through
        the task queue. Used when immediate results are needed.

        Args:
            req: Import request with kind, kb_id, and source-specific params

        Returns:
            Import stats dict with files, nodes, failed counts

        Raises:
            ValueError: If required fields are missing for the given kind
        """
        if req.kind == "generic":
            if req.paths and len(req.paths) > 1:
                merged = {"files": 0, "nodes": 0, "failed": 0}
                for item in req.paths:
                    stats = GenericService.import_file(
                        kb_id=req.kb_id,
                        path=item,
                        refresh_topics=False,
                    )
                    merged["files"] += stats.get("files", 0)
                    merged["nodes"] += stats.get("nodes", 0)
                    merged["failed"] += stats.get("failed", 0)
                if req.refresh_topics:
                    from kb_core.services import KnowledgeBaseService

                    KnowledgeBaseService.refresh_topics(
                        req.kb_id, has_new_docs=merged["files"] > 0
                    )
                return merged

            path = req.path or (req.paths[0] if req.paths else None)
            if not path:
                raise ValueError("generic 同步导入缺少 path")
            return GenericService.import_file(
                kb_id=req.kb_id,
                path=path,
                refresh_topics=req.refresh_topics,
            )

        if req.kind == "obsidian":
            if not req.vault_path:
                raise ValueError("obsidian 同步导入缺少 vault_path")
            return ObsidianService.import_vault(
                kb_id=req.kb_id,
                vault_path=req.vault_path,
                folder_path=req.folder_path,
                recursive=req.recursive,
                exclude_patterns=req.exclude_patterns,
                rebuild=req.rebuild,
                refresh_topics=req.refresh_topics,
                force_delete=req.force_delete if req.force_delete is not None else True,
            )

        if req.kind == "zotero":
            return ZoteroService.import_collection(
                kb_id=req.kb_id,
                collection_id=req.collection_id,
                collection_name=req.collection_name,
                rebuild=req.rebuild,
                refresh_topics=req.refresh_topics,
            )

        raise ValueError(f"不支持的导入类型: {req.kind}")
