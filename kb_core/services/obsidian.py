from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from rag.config import get_settings
from rag.logger import get_logger
from rag.ollama_utils import (
    create_parallel_ollama_embedding,
    configure_global_embed_model,
)

logger = get_logger(__name__)

from .vector_store import VectorStoreService
from .knowledge_base import KnowledgeBaseService

class ObsidianService:
    """Obsidian 导入服务"""

    @staticmethod
    def get_vaults() -> List[Dict[str, Any]]:
        """获取可用的 Obsidian Vault 列表"""
        from kb_core.registry import get_vault_root

        vault_path = str(get_vault_root())

        vaults = [
            {
                "name": "默认",
                "path": vault_path,
            },
        ]

        try:
            from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

            configured_paths = set()
            for mapping in OBSIDIAN_KB_MAPPINGS:
                if hasattr(mapping, "vault_path") and mapping.vault_path:
                    configured_paths.add(mapping.vault_path)

            for path in configured_paths:
                if path != vault_path:
                    vaults.append({"name": f"配置 ({Path(path).name})", "path": path})
        except ImportError:
            pass

        result = []
        for v in vaults:
            path = Path(v["path"])
            if path.exists():
                md_count = len(list(path.rglob("*.md")))
                result.append(
                    {
                        **v,
                        "exists": True,
                        "md_files": md_count,
                    }
                )
            else:
                result.append(
                    {
                        **v,
                        "exists": False,
                        "md_files": 0,
                    }
                )

        return result

    @staticmethod
    def get_vault_info(vault_name: str) -> Optional[Dict[str, Any]]:
        """获取 Vault 信息"""
        from kb_core.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

                configured_path = None
                for mapping in OBSIDIAN_KB_MAPPINGS:
                    if hasattr(mapping, "vault_path") and mapping.vault_path:
                        expected_name = f"配置 ({Path(mapping.vault_path).name})"
                        if vault_name == expected_name:
                            configured_path = mapping.vault_path
                            break

                if configured_path:
                    vault_path = Path(configured_path)
                else:
                    return None
            except ImportError:
                return None

        if not vault_path.exists():
            return None

        folders = {}
        for item in vault_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                md_count = len(list(item.rglob("*.md")))
                if md_count > 0:
                    folders[item.name] = md_count

        return {
            "name": vault_name,
            "path": str(vault_path),
            "total_md_files": len(list(vault_path.rglob("*.md"))),
            "folders": folders,
        }

    @staticmethod
    def get_vault_structure(
        vault_name: str, folder_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取 Vault 文件夹的层级结构

        Args:
            vault_name: Vault 名称
            folder_path: 子文件夹路径（None 表示根目录）

        Returns:
            层级结构
        """
        from kb_core.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

                configured_path = None
                for mapping in OBSIDIAN_KB_MAPPINGS:
                    if hasattr(mapping, "vault_path") and mapping.vault_path:
                        expected_name = f"配置 ({Path(mapping.vault_path).name})"
                        if vault_name == expected_name:
                            configured_path = mapping.vault_path
                            break

                if configured_path:
                    vault_path = Path(configured_path)
                else:
                    return {"error": f"未找到 Vault: {vault_name}"}
            except ImportError:
                return {"error": "无法加载 Vault 配置"}

        if not vault_path.exists():
            return {"error": f"Vault 路径不存在: {vault_path}"}

        target_dir = vault_path if not folder_path else vault_path / folder_path
        if not target_dir.exists():
            return {"error": f"文件夹不存在: {target_dir}"}

        items = []
        for item in sorted(target_dir.iterdir()):
            if item.name.startswith("."):
                continue

            if item.is_dir():
                md_count = len(list(item.glob("*.md")))
                items.append(
                    {
                        "type": "folder",
                        "name": item.name,
                        "path": str(item.relative_to(vault_path)),
                        "md_count": md_count,
                    }
                )
            elif item.suffix == ".md":
                size = item.stat().st_size
                items.append(
                    {
                        "type": "file",
                        "name": item.name,
                        "path": str(item.relative_to(vault_path)),
                        "size": size,
                    }
                )

        return {
            "vault_name": vault_name,
            "vault_path": str(vault_path),
            "folder_path": folder_path or "",
            "items": items,
        }

    @staticmethod
    def get_vault_tree(vault_name: str) -> Dict[str, Any]:
        """
        获取 Vault 的完整树形结构（仅顶层文件夹，用于懒加载）

        Args:
            vault_name: Vault 名称

        Returns:
            树形结构
        """
        from kb_core.registry import get_vault_root

        if vault_name == "默认":
            vault_path = get_vault_root()
        else:
            try:
                from kb_obsidian.config import OBSIDIAN_KB_MAPPINGS

                configured_path = None
                for mapping in OBSIDIAN_KB_MAPPINGS:
                    if hasattr(mapping, "vault_path") and mapping.vault_path:
                        expected_name = f"配置 ({Path(mapping.vault_path).name})"
                        if vault_name == expected_name:
                            configured_path = mapping.vault_path
                            break

                if configured_path:
                    vault_path = Path(configured_path)
                else:
                    return {"error": f"未找到 Vault: {vault_name}"}
            except ImportError:
                return {"error": "无法加载 Vault 配置"}

        if not vault_path.exists():
            return {"error": f"Vault 路径不存在: {vault_path}"}

        def build_tree(dir_path: Path, depth: int = 0) -> List[Dict[str, Any]]:
            if depth > 3:
                return []

            result = []
            for item in sorted(dir_path.iterdir()):
                if item.name.startswith("."):
                    continue

                if item.is_dir():
                    md_count = len(list(item.glob("*.md")))
                    children = build_tree(item, depth + 1) if depth < 2 else []
                    result.append(
                        {
                            "type": "folder",
                            "name": item.name,
                            "path": str(item.relative_to(vault_path)),
                            "md_count": md_count,
                            "has_children": len(children) > 0,
                            "children": children,
                        }
                    )
                elif item.suffix == ".md":
                    result.append(
                        {
                            "type": "file",
                            "name": item.name,
                            "path": str(item.relative_to(vault_path)),
                            "size": item.stat().st_size,
                        }
                    )

            return result

        return {
            "vault_name": vault_name,
            "vault_path": str(vault_path),
            "items": build_tree(vault_path),
        }

    @staticmethod
    def import_vault(
        kb_id: str,
        vault_path: str,
        folder_path: Optional[str] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
        rebuild: bool = False,
        refresh_topics: bool = True,
        force_delete: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
        chunk_strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        hierarchical_chunk_sizes: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        导入 Obsidian 笔记

        Args:
            kb_id: 知识库 ID
            vault_path: Vault 根路径
            folder_path: 子文件夹路径
            recursive: 是否递归
            exclude_patterns: 排除模式
            rebuild: 是否重建
            progress_callback: 进度回调
            chunk_strategy: 分块策略
            chunk_size: 分块大小
            hierarchical_chunk_sizes: 层级分块大小列表

        Returns:
            导入统计
        """
        from kb_obsidian.processor import ObsidianImporter
        from kb_processing.document_processor import DocumentProcessorConfig

        vault_path = Path(vault_path)
        if not vault_path.exists():
            raise ValueError(f"Vault 路径不存在: {vault_path}")

        import_dir = vault_path
        if folder_path:
            import_dir = vault_path / folder_path
            if not import_dir.exists():
                raise ValueError(f"文件夹不存在: {import_dir}")

        # 获取向量存储
        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = VectorStoreService.get_persist_dir(kb_id)

        settings = get_settings()
        config = DocumentProcessorConfig(
            chunk_size=chunk_size or settings.chunk_size,
            chunk_strategy=chunk_strategy or settings.chunk_strategy,
            hierarchical_chunk_sizes=hierarchical_chunk_sizes or settings.hierarchical_chunk_sizes,
        )
        importer = ObsidianImporter(
            vault_root=vault_path,
            kb_id=kb_id,
            persist_dir=persist_dir,
            config=config,
        )

        exclude_patterns = exclude_patterns or [
            "*/image/*",
            "*/_resources/*",
            "*/.obsidian/*",
            "*/.trash/*",
            "*/Z_Copilot/*",
            "*/copilot-custom-prompts/*",
        ]
        importer.exclude_patterns = exclude_patterns

        if progress_callback:
            progress_callback(f"开始导入 Obsidian: {import_dir.name}")

        try:
            stats = importer.import_directory(
                directory=import_dir,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
                progress=None,
                rebuild=rebuild,
                exclude_patterns=exclude_patterns,
                recursive=recursive,
                force_delete=force_delete,
            )

            if progress_callback:
                progress_callback(
                    f"完成！导入 {stats.get('files', 0)} 个文件，{stats.get('nodes', 0)} 个节点"
                )

            if refresh_topics:
                KnowledgeBaseService.refresh_topics(
                    kb_id=kb_id,
                    has_new_docs=stats.get("files", 0) > 0,
                )
            return stats

        finally:
            pass  # ObsidianImporter 不需要关闭

# =============================================================================
