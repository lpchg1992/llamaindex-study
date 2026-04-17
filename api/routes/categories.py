"""
Category rules management endpoints.
"""

from typing import Optional, Dict, Any

from fastapi import APIRouter, Query

from api.schemas import (
    FilePreviewRequest,
    FilePreviewResponse,
    FilePreviewItem,
)

router = APIRouter(tags=["categories"])


@router.get("/category/rules")
def list_category_rules():
    from kb_core.database import init_category_rule_db

    rule_db = init_category_rule_db()
    rules = rule_db.get_all_rules()

    return {
        "rules": rules,
        "total": len(rules),
    }


@router.post("/category/rules/sync")
def sync_category_rules():
    from kb_obsidian.config import seed_mappings_to_db

    count = seed_mappings_to_db()

    return {
        "status": "success",
        "message": f"已同步 {count} 条分类规则到数据库",
    }


@router.post("/category/classify")
def classify_folder_llm(
    folder_path: str = Query(""),
    folder_description: str = Query(""),
    use_llm: bool = Query(True),
    request: Optional[Dict] = None,
):
    if request is not None:
        folder_path = request.get("folder_path", folder_path)
        folder_description = request.get("folder_description", folder_description)
        use_llm = request.get("use_llm", use_llm)

    if not folder_path:
        return {"error": "folder_path is required"}
    from kb_obsidian.config import find_kb_by_path
    from kb_analysis.category_classifier import CategoryClassifier

    matched_kbs = find_kb_by_path(folder_path)

    if matched_kbs and not use_llm:
        return {
            "kb_id": matched_kbs[0],
            "matched_by": "rule",
            "confidence": 1.0,
            "reason": f"文件夹路径匹配: {folder_path}",
        }

    if use_llm:
        try:
            classifier = CategoryClassifier()
            result = classifier.classify_folder_llm(
                folder_path=folder_path,
                folder_description=folder_description,
            )

            return {
                "kb_id": result["kb_id"],
                "matched_by": "llm",
                "confidence": result["confidence"],
                "reason": result["reason"],
                "alternatives": matched_kbs if matched_kbs else None,
            }
        except Exception as e:
            return {
                "error": f"LLM 分类失败: {str(e)}",
                "alternatives": matched_kbs,
            }

    return {
        "kb_id": None,
        "matched_by": "none",
        "confidence": 0.0,
        "reason": "未找到匹配的知识库",
        "suggestion": "请手动指定知识库或使用 LLM 分类",
    }


@router.post("/category/rules/add")
def add_category_rule(
    kb_id: str = Query(...),
    rule_type: str = Query(...),
    pattern: str = Query(...),
    description: str = Query(""),
    priority: int = Query(0),
):
    from kb_core.database import init_category_rule_db

    rule_db = init_category_rule_db()
    success = rule_db.add_rule(
        kb_id=kb_id,
        rule_type=rule_type,
        pattern=pattern,
        description=description,
        priority=priority,
    )

    return {
        "status": "success" if success else "error",
        "message": f"规则添加{'成功' if success else '失败'}",
    }


@router.post("/file/preview", response_model=FilePreviewResponse)
def preview_file_import(req: FilePreviewRequest):
    from pathlib import Path
    from typing import List
    from kb_processing.generic_processor import GenericImporter

    importer = GenericImporter()
    filtering_rules = []
    warnings = []
    all_files: List[Path] = []

    for path_str in req.paths:
        p = Path(path_str)
        if not p.exists():
            warnings.append(f"路径不存在: {path_str}")
            continue
        if p.is_file():
            all_files.append(p)
        elif p.is_dir():
            files = importer.collect_files(
                [p],
                include_exts=req.include_exts or [],
                exclude_exts=req.exclude_exts or [],
            )
            all_files.extend(files)

    total_items = len(all_files)

    if req.include_exts:
        filtering_rules.append(f"只处理扩展名: {', '.join(req.include_exts)}")
    if req.exclude_exts:
        filtering_rules.append(f"排除扩展名: {', '.join(req.exclude_exts)}")
    if not req.include_exts and not req.exclude_exts:
        filtering_rules.append("使用默认扩展名: pdf, docx, xlsx, md, txt 等")

    filtering_rules.append(f"共找到 {total_items} 个文件")

    preview_items = [
        FilePreviewItem(
            path=str(f),
            name=f.name,
            size=f.stat().st_size,
        )
        for f in all_files[:50]
    ]

    return FilePreviewResponse(
        total_items=total_items,
        eligible_items=total_items,
        filtering_rules=filtering_rules,
        items=preview_items,
        warnings=warnings,
    )