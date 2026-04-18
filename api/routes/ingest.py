"""
Document ingestion endpoints.
"""

from typing import List

from fastapi import APIRouter, HTTPException

from api.schemas import (
    IngestRequest,
    IngestResponse,
    ZoteroIngestRequest,
    ObsidianIngestRequest,
    SelectiveImportRequest,
    FilesImportRequest,
)
from rag.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["ingest"])


@router.post("/kbs/{kb_id}/ingest")
def ingest(kb_id: str, req: IngestRequest):
    from pathlib import Path
    from kb_core.import_service import ImportApplicationService, ImportRequest
    from kb_processing.generic_processor import GenericImporter

    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"路径不存在: {req.path}")

    all_files: List[Path] = []
    if path.is_file():
        all_files.append(path)
    elif path.is_dir():
        importer = GenericImporter()
        all_files = importer.collect_files([path], recursive=True)

    if not all_files:
        raise HTTPException(
            status_code=400,
            detail=f"没有找到可处理的文件: {req.path}",
        )

    if not req.async_mode:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="generic",
                kb_id=kb_id,
                async_mode=False,
                path=req.path,
                refresh_topics=req.refresh_topics,
                chunk_strategy=req.chunk_strategy,
                chunk_size=req.chunk_size,
                hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
            )
        )
        return IngestResponse(
            status="completed",
            files_processed=stats.get("files", 0),
            nodes_created=stats.get("nodes", 0),
            failed=stats.get("failed", 0),
            message="同步导入完成",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="generic",
            kb_id=kb_id,
            path=req.path,
            refresh_topics=req.refresh_topics,
            source=req.path,
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
        )
    )

    task_id = task["task_id"]
    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"导入任务已提交，ID: {task_id}，文件数: {len(all_files)}",
    )


@router.post("/kbs/{kb_id}/ingest/zotero", response_model=IngestResponse)
def ingest_zotero(kb_id: str, req: ZoteroIngestRequest):
    from kb_zotero.processor import ZoteroImporter
    from kb_core.import_service import ImportApplicationService, ImportRequest

    importer = ZoteroImporter()
    collection_id = req.collection_id
    collection_name = req.collection_name or "Unknown"

    if not collection_id and req.collection_name:
        result = importer.get_collection_by_name(req.collection_name)
        if result and "collectionID" in result:
            collection_id = result["collectionID"]
            collection_name = result.get("collectionName", collection_name)
        elif result and "multiple" in result:
            importer.close()
            raise HTTPException(
                status_code=400,
                detail="名称模糊，存在多个匹配，请用 collection_id 精确指定",
            )
        else:
            importer.close()
            raise HTTPException(
                status_code=400, detail=f"未找到收藏夹: {req.collection_name}"
            )

    importer.close()

    if not req.async_mode:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="zotero",
                kb_id=kb_id,
                async_mode=False,
                collection_id=collection_id,
                collection_name=collection_name,
                rebuild=req.rebuild,
                refresh_topics=req.refresh_topics,
                chunk_strategy=req.chunk_strategy,
                chunk_size=req.chunk_size,
                hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
            )
        )
        return IngestResponse(
            status="completed",
            files_processed=stats.get("items", 0),
            nodes_created=stats.get("nodes", 0),
            failed=stats.get("failed", 0),
            message="同步导入完成",
            source="zotero",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="zotero",
            kb_id=kb_id,
            collection_id=collection_id,
            collection_name=collection_name,
            rebuild=req.rebuild,
            refresh_topics=req.refresh_topics,
            source=f"zotero:{collection_name}",
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
        )
    )
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"Zotero {collection_name} 导入任务已提交，ID: {task_id}",
        source="zotero",
    )


@router.post("/kbs/{kb_id}/ingest/obsidian", response_model=IngestResponse)
def ingest_obsidian(kb_id: str, req: ObsidianIngestRequest):
    from pathlib import Path
    from kb_core.import_service import ImportApplicationService, ImportRequest

    vault_path_obj = Path(req.vault_path) if req.vault_path else None
    if vault_path_obj and not vault_path_obj.exists():
        raise HTTPException(
            status_code=400, detail=f"Vault 路径不存在: {req.vault_path}"
        )

    import_dir = vault_path_obj
    if req.folder_path and vault_path_obj:
        import_dir = vault_path_obj / req.folder_path
        if not import_dir.exists():
            raise HTTPException(
                status_code=400, detail=f"文件夹路径不存在: {req.folder_path}"
            )

    vault_name = vault_path_obj.name if vault_path_obj else "unknown"
    import_dir_name = import_dir.name if import_dir else "unknown"

    if not req.async_mode:
        stats = ImportApplicationService.run_sync(
            ImportRequest(
                kind="obsidian",
                kb_id=kb_id,
                async_mode=False,
                vault_path=str(vault_path_obj) if vault_path_obj else None,
                folder_path=req.folder_path,
                recursive=req.recursive,
                exclude_patterns=req.exclude_patterns,
                refresh_topics=req.refresh_topics,
                chunk_strategy=req.chunk_strategy,
                chunk_size=req.chunk_size,
                hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
            )
        )
        return IngestResponse(
            status="completed",
            files_processed=stats.get("files", 0),
            nodes_created=stats.get("nodes", 0),
            failed=stats.get("failed", 0),
            message="同步导入完成",
            source="obsidian",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="obsidian",
            kb_id=kb_id,
            vault_path=str(vault_path_obj) if vault_path_obj else None,
            folder_path=req.folder_path,
            recursive=req.recursive,
            exclude_patterns=req.exclude_patterns,
            refresh_topics=req.refresh_topics,
            source=f"obsidian:{import_dir_name}",
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
        )
    )
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"Obsidian {import_dir_name} 导入任务已提交，ID: {task_id}",
        source="obsidian",
    )


@router.post("/kbs/{kb_id}/ingest/selective", response_model=IngestResponse)
def ingest_selective(kb_id: str, req: SelectiveImportRequest):
    valid_source_types = {"zotero", "obsidian", "files"}
    if req.source_type not in valid_source_types:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 source_type: {req.source_type}，有效值: {valid_source_types}",
        )

    from kb_core.import_service import (
        ImportApplicationService,
        SelectiveImportItem,
        SelectiveImportRequest as ServiceSelectiveRequest,
    )

    items = [
        SelectiveImportItem(
            type=item.get("type", ""),
            id=item.get("id"),
            path=item.get("path"),
            options=item.get("options", {}),
        )
        for item in req.items
    ]

    service_req = ServiceSelectiveRequest(
        source_type=req.source_type,
        items=items,
        async_mode=req.async_mode,
        refresh_topics=req.refresh_topics,
        prefix=req.prefix,
    )

    task = ImportApplicationService.submit_selective_import(kb_id, service_req)
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"选择性导入任务已提交，ID: {task_id}，项目数: {len(items)}",
        source=req.source_type,
    )


@router.post("/kbs/{kb_id}/ingest/files", response_model=IngestResponse)
def ingest_files(kb_id: str, req: FilesImportRequest):
    from pathlib import Path
    from kb_core.services import KnowledgeBaseService, GenericService
    from kb_core.import_service import ImportApplicationService, ImportRequest
    from rag.logger import get_logger

    logger = get_logger(__name__)
    validated_paths = []
    for path_str in req.paths:
        p = Path(path_str)
        if not p.exists():
            raise HTTPException(status_code=400, detail=f"文件不存在: {path_str}")
        validated_paths.append(str(p))

    if not validated_paths:
        raise HTTPException(status_code=400, detail="没有提供有效的文件路径")

    if not req.async_mode:
        merged = {"files": 0, "nodes": 0, "failed": 0}
        for path in validated_paths:
            try:
                stats = GenericService.import_file(
                    kb_id=kb_id,
                    path=path,
                    refresh_topics=False,
                )
                merged["files"] += stats.get("files", 0)
                merged["nodes"] += stats.get("nodes", 0)
                merged["failed"] += stats.get("failed", 0)
            except Exception as e:
                merged["failed"] += 1
                logger.error(f"导入文件失败 {path}: {e}")

        if req.refresh_topics and merged["files"] > 0:
            KnowledgeBaseService.refresh_topics(kb_id, has_new_docs=True)

        return IngestResponse(
            status="completed",
            files_processed=merged.get("files", 0),
            nodes_created=merged.get("nodes", 0),
            failed=merged.get("failed", 0),
            message="同步导入完成",
            source="files",
        )

    task = ImportApplicationService.submit_task(
        ImportRequest(
            kind="generic",
            kb_id=kb_id,
            paths=validated_paths,
            refresh_topics=req.refresh_topics,
            source=f"files:{len(validated_paths)}files",
            chunk_strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            hierarchical_chunk_sizes=req.hierarchical_chunk_sizes,
        )
    )
    task_id = task["task_id"]

    return IngestResponse(
        status="pending",
        task_id=task_id,
        message=f"文件导入任务已提交，ID: {task_id}，文件数: {len(validated_paths)}",
        source="files",
    )