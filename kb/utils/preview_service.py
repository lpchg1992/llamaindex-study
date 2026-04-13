"""
任务预览服务

在任务提交前显示将要处理的文件/文献列表和筛选规则，
帮助用户在执行前确认范围是否符合预期。
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class PreviewResult:
    kind: str
    kb_id: str
    total_items: int
    eligible_items: int
    filtering_rules: List[str]
    preview_items: List[Dict[str, Any]]
    warnings: List[str]


class PreviewService:
    """任务预览服务"""

    def preview_zotero(
        self,
        collection_id: Optional[int] = None,
        collection_name: Optional[str] = None,
        kb_id: str = "default",
        limit: int = 10,
    ) -> PreviewResult:
        """预览 Zotero 收藏夹的处理范围

        Args:
            collection_id: 收藏夹 ID
            collection_name: 收藏夹名称（用于查询 ID）
            kb_id: 知识库 ID
            limit: 预览条数

        Returns:
            PreviewResult: 预览结果
        """
        from kb.zotero_processor import ZoteroImporter

        importer = ZoteroImporter()
        warnings = []

        if collection_name and not collection_id:
            result = importer.get_collection_by_name(collection_name)
            if result and "collectionID" in result:
                collection_id = result["collectionID"]
            else:
                return PreviewResult(
                    kind="zotero",
                    kb_id=kb_id,
                    total_items=0,
                    eligible_items=0,
                    filtering_rules=[f"收藏夹未找到: {collection_name}"],
                    preview_items=[],
                    warnings=[f"收藏夹不存在: {collection_name}"],
                )

        if not collection_id:
            return PreviewResult(
                kind="zotero",
                kb_id=kb_id,
                total_items=0,
                eligible_items=0,
                filtering_rules=["缺少 collection_id 或 collection_name"],
                preview_items=[],
                warnings=["需要提供 collection_id 或 collection_name"],
            )

        all_items = importer.get_items_in_collection(collection_id, recursive=True)
        total_items = len(all_items)

        eligible_items = []
        ineligible_items = []

        from kb.document_processor import DocumentProcessor

        processor = DocumentProcessor()

        for item_id in all_items:
            item = importer.get_item(item_id)
            if not item:
                warnings.append(f"文献不存在: item_id={item_id}")
                continue

            attachment_path = importer._get_attachment_path(item_id)
            if attachment_path:
                is_pdf = attachment_path.lower().endswith(".pdf")
                is_scanned = False
                if is_pdf:
                    try:
                        is_scanned = processor.is_scanned_pdf(attachment_path)
                    except Exception as e:
                        warnings.append(f"扫描检测失败 item={item_id}: {e}")

                md_cache_path = None
                if is_pdf and attachment_path:
                    md_cache_path = (
                        Path("/Volumes/online/llamaindex/mddocs")
                        / f"{Path(attachment_path).stem}.md"
                    )
                has_md_cache = (
                    md_cache_path.exists() and md_cache_path.stat().st_size > 100
                    if md_cache_path
                    else False
                )

                eligible_items.append(
                    {
                        "item_id": item_id,
                        "title": item.title[:80],
                        "creators": item.creators[:3],
                        "has_attachment": True,
                        "attachment_path": attachment_path,
                        "is_pdf": is_pdf,
                        "is_scanned": is_scanned,
                        "has_md_cache": has_md_cache,
                        "options": {
                            "is_scanned": is_scanned,
                            "force_ocr": False,
                            "has_md_cache": has_md_cache,
                        },
                    }
                )
            else:
                ineligible_items.append(
                    {
                        "item_id": item_id,
                        "title": item.title[:80],
                        "has_attachment": False,
                    }
                )

        filtering_rules = [
            "附件标题必须包含 [kb] 前缀",
            f"收藏夹内共 {total_items} 篇文献",
            f"有 [kb] 标记的: {len(eligible_items)} 篇",
            f"无 [kb] 标记将被跳过: {len(ineligible_items)} 篇",
        ]

        return PreviewResult(
            kind="zotero",
            kb_id=kb_id,
            total_items=total_items,
            eligible_items=len(eligible_items),
            filtering_rules=filtering_rules,
            preview_items=eligible_items[:limit],
            warnings=warnings,
        )

    def preview_file(
        self,
        paths: List[str],
        kb_id: str = "default",
        include_exts: Optional[List[str]] = None,
        exclude_exts: Optional[List[str]] = None,
        limit: int = 20,
    ) -> PreviewResult:
        """预览文件导入的处理范围

        Args:
            paths: 文件或目录路径列表
            kb_id: 知识库 ID
            include_exts: 只包含指定的扩展名
            exclude_exts: 排除指定的扩展名
            limit: 预览条数

        Returns:
            PreviewResult: 预览结果
        """
        from kb.generic_processor import GenericImporter

        importer = GenericImporter()
        filtering_rules = []
        warnings = []
        all_files: List[Path] = []

        for path_str in paths:
            p = Path(path_str)
            if not p.exists():
                warnings.append(f"路径不存在: {path_str}")
                continue
            if p.is_file():
                all_files.append(p)
            elif p.is_dir():
                files = importer.collect_files(
                    [p],
                    include_exts=include_exts or [],
                    exclude_exts=exclude_exts or [],
                )
                all_files.extend(files)

        total_items = len(all_files)

        if include_exts:
            filtering_rules.append(f"只处理扩展名: {', '.join(include_exts)}")
        if exclude_exts:
            filtering_rules.append(f"排除扩展名: {', '.join(exclude_exts)}")
        if not include_exts and not exclude_exts:
            filtering_rules.append("使用默认扩展名: pdf, docx, xlsx, md, txt 等")

        filtering_rules.append(f"共找到 {total_items} 个文件")

        preview_items = [
            {"path": f.name, "size": f.stat().st_size} for f in all_files[:limit]
        ]

        return PreviewResult(
            kind="file",
            kb_id=kb_id,
            total_items=total_items,
            eligible_items=total_items,
            filtering_rules=filtering_rules,
            preview_items=preview_items,
            warnings=warnings,
        )

    def preview_obsidian(
        self,
        vault_path: str,
        kb_id: str = "default",
        limit: int = 20,
    ) -> PreviewResult:
        """预览 Obsidian 导入的处理范围

        Args:
            vault_path: Vault 路径
            kb_id: 知识库 ID
            limit: 预览条数

        Returns:
            PreviewResult: 预览结果
        """
        vault = Path(vault_path)
        filtering_rules = [
            "只处理 .md 文件",
            "忽略以 _ 开头的目录（Obsidian 约定）",
        ]

        if not vault.exists():
            return PreviewResult(
                kind="obsidian",
                kb_id=kb_id,
                total_items=0,
                eligible_items=0,
                filtering_rules=filtering_rules,
                preview_items=[],
                warnings=[f"Vault 路径不存在: {vault_path}"],
            )

        md_files = list(vault.rglob("*.md"))
        md_files = [
            f for f in md_files if not any(p.name.startswith("_") for p in f.parents)
        ]

        total_items = len(md_files)
        filtering_rules.append(f"共找到 {total_items} 个 .md 文件")

        preview_items = [
            {"path": str(f.relative_to(vault)), "size": f.stat().st_size}
            for f in md_files[:limit]
        ]

        return PreviewResult(
            kind="obsidian",
            kb_id=kb_id,
            total_items=total_items,
            eligible_items=total_items,
            filtering_rules=filtering_rules,
            preview_items=preview_items,
            warnings=[],
        )
