"""
Zotero integration endpoints.
"""

from typing import Optional, List

from fastapi import APIRouter, HTTPException

from api.schemas import (
    ZoteroPreviewRequest,
    ZoteroPreviewResponse,
    ZoteroPreviewItem,
)

router = APIRouter(prefix="/zotero", tags=["zotero"])


@router.get("/collections")
def list_zotero_collections():
    from kb_core.services import ZoteroService

    collections = ZoteroService.list_collections()
    return {"collections": collections}


@router.get("/collections/search")
def search_zotero_collections(q: str):
    from kb_core.services import ZoteroService

    results = ZoteroService.search_collections(q)
    return {"results": results}


@router.get("/collections/{collection_id}/structure")
def get_zotero_collection_structure(collection_id: str):
    from kb_core.services import ZoteroService

    result = ZoteroService.get_collection_structure(collection_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/collections/with-items")
def get_all_collections_with_items():
    from kb_core.services import ZoteroService

    return {"collections": ZoteroService.get_all_collections_with_items()}


@router.post("/preview", response_model=ZoteroPreviewResponse)
def preview_zotero_import(req: ZoteroPreviewRequest):
    from pathlib import Path
    from kb_zotero.processor import ZoteroImporter
    from kb_core.database import init_document_db
    from kb_core.services import KnowledgeBaseService

    importer = ZoteroImporter()
    mddocs_base = Path("/Volumes/online/llamaindex/mddocs")

    document_db = None
    kb_info = KnowledgeBaseService.get_info(req.kb_id)
    if kb_info and Path(kb_info.get("persist_dir", "")).exists():
        try:
            document_db = init_document_db()
        except Exception:
            pass

    item_ids = list(req.item_ids) if req.item_ids else []

    if req.collection_id and not item_ids:
        try:
            col_id = int(req.collection_id)
            item_ids = importer.get_items_in_collection(col_id, recursive=True)
        except (ValueError, TypeError):
            pass

    prefix = req.prefix or "[kb]"
    include_exts = req.include_exts
    filtering_rules = [
        f"附件标题必须包含 {prefix} 前缀才会被导入",
        "已导入的文献会被跳过（通过 document 表查询）",
    ]
    if include_exts:
        filtering_rules.append(f"只导入扩展名: {', '.join(include_exts)}")

    eligible_items = []
    ineligible_items = []
    duplicate_items = []

    for item_id in item_ids:
        item = importer.get_item(item_id, prefix=prefix)
        if not item:
            continue

        attachment_path = item.file_path

        preview_item = ZoteroPreviewItem(
            item_id=item_id,
            title=item.title,
            creators=item.creators[:3],
            has_attachment=bool(attachment_path),
            attachment_path=attachment_path,
        )

        if not attachment_path:
            preview_item.is_eligible = False
            preview_item.ineligible_reason = f"附件标题不含 {prefix} 标记"
            ineligible_items.append(preview_item)
            continue

        zotero_doc_id = str(item_id)

        if document_db:
            existing_doc = document_db.get_by_zotero_doc_id(req.kb_id, zotero_doc_id)
            if existing_doc:
                preview_item.is_duplicate = True
                preview_item.ineligible_reason = (
                    f"文献已导入（zotero_doc_id: {zotero_doc_id}）"
                )
                duplicate_items.append(preview_item)
                continue

        ext = Path(attachment_path).suffix.lower() if attachment_path else ""
        preview_item.attachment_type = ext.lstrip(".")

        if include_exts and ext.lstrip(".") not in include_exts:
            preview_item.is_eligible = False
            preview_item.ineligible_reason = f"扩展名 {ext.lstrip('.')} 不在筛选范围内"
            ineligible_items.append(preview_item)
            continue

        if ext == ".pdf" and attachment_path:
            pdf_path = Path(attachment_path)
            if pdf_path.exists():
                is_scanned = importer.processor.is_scanned_pdf(str(pdf_path))
                preview_item.is_scanned_pdf = is_scanned

                md_cache_path = mddocs_base / f"{pdf_path.stem}.md"
                preview_item.has_md_cache = (
                    md_cache_path.exists() and md_cache_path.stat().st_size > 100
                )

        preview_item.is_eligible = True
        eligible_items.append(preview_item)

    importer.close()

    return ZoteroPreviewResponse(
        total_items=len(item_ids),
        eligible_items=len(eligible_items),
        ineligible_items=len(ineligible_items),
        duplicate_items=len(duplicate_items),
        items=eligible_items + ineligible_items + duplicate_items,
        filtering_rules=filtering_rules,
    )