"""
Obsidian integration endpoints.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from api.schemas import (
    ObsidianPreviewRequest,
    ObsidianPreviewResponse,
    ObsidianPreviewItem,
)
from kb_core.import_service import ImportApplicationService, ImportRequest

router = APIRouter(prefix="/obsidian", tags=["obsidian"])


@router.get("/vaults")
def list_obsidian_vaults():
    from kb_core.services import ObsidianService

    vaults = ObsidianService.get_vaults()
    return {"vaults": vaults}


@router.get("/vaults/{vault_name}")
def get_obsidian_vault(vault_name: str):
    from kb_core.services import ObsidianService

    info = ObsidianService.get_vault_info(vault_name)
    if not info:
        raise HTTPException(status_code=404, detail="Vault not found")
    return info


@router.get("/vaults/{vault_name}/structure")
def get_obsidian_vault_structure(vault_name: str, folder_path: Optional[str] = None):
    from kb_core.services import ObsidianService

    result = ObsidianService.get_vault_structure(vault_name, folder_path)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/vaults/{vault_name}/tree")
def get_obsidian_vault_tree(vault_name: str):
    from kb_core.services import ObsidianService

    result = ObsidianService.get_vault_tree(vault_name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/mappings")
def list_obsidian_mappings():
    from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

    return {
        "mappings": [
            {
                "kb_id": m.kb_id,
                "name": m.name,
                "folders": m.folders,
                "description": m.description,
            }
            for m in OBSIDIAN_KB_MAPPINGS
        ]
    }


@router.post("/import-all")
def import_obsidian_all():
    from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS
    from kb_core.registry import get_vault_root

    task_ids = []
    vault_root = get_vault_root()
    if not vault_root.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Vault 根目录不存在: {vault_root}",
        )

    for mapping in OBSIDIAN_KB_MAPPINGS:
        if not mapping.folders:
            continue

        for folder in mapping.folders:
            task = ImportApplicationService.submit_task(
                ImportRequest(
                    kind="obsidian",
                    kb_id=mapping.kb_id,
                    vault_path=str(vault_root),
                    folder_path=folder,
                    recursive=True,
                    refresh_topics=True,
                    source=f"obsidian:{folder}",
                )
            )
            task_id = task["task_id"]

            task_ids.append(
                {
                    "kb_id": mapping.kb_id,
                    "folder": folder,
                    "task_id": task_id,
                }
            )

    return {
        "status": "pending",
        "message": f"已提交 {len(task_ids)} 个文件夹导入任务",
        "tasks": task_ids,
    }


@router.post("/preview", response_model=ObsidianPreviewResponse)
def preview_obsidian_import(req: ObsidianPreviewRequest):
    from pathlib import Path

    vault = Path(req.vault_path)
    filtering_rules = [
        "只处理 .md 文件",
        "忽略以 _ 开头的目录（Obsidian 约定）",
    ]
    warnings = []

    if not vault.exists():
        return ObsidianPreviewResponse(
            total_items=0,
            eligible_items=0,
            filtering_rules=filtering_rules,
            items=[],
            warnings=[f"Vault 路径不存在: {req.vault_path}"],
        )

    import_dir = vault
    if req.folder_path:
        import_dir = vault / req.folder_path
        if not import_dir.exists():
            return ObsidianPreviewResponse(
                total_items=0,
                eligible_items=0,
                filtering_rules=filtering_rules,
                items=[],
                warnings=[f"文件夹路径不存在: {req.folder_path}"],
            )

    md_files = list(import_dir.rglob("*.md"))
    md_files = [
        f for f in md_files if not any(p.name.startswith("_") for p in f.parents)
    ]

    prefix = req.prefix
    if prefix:
        md_files = [f for f in md_files if f.name.startswith(prefix)]
        filtering_rules.append(f"只导入文件名前缀为 '{prefix}' 的文件")

    total_items = len(md_files)
    filtering_rules.append(f"共找到 {total_items} 个 .md 文件")

    preview_items = [
        ObsidianPreviewItem(
            path=str(f),
            relative_path=str(f.relative_to(import_dir)),
            size=f.stat().st_size,
        )
        for f in md_files[:50]
    ]

    return ObsidianPreviewResponse(
        total_items=total_items,
        eligible_items=total_items,
        filtering_rules=filtering_rules,
        items=preview_items,
        warnings=warnings,
    )