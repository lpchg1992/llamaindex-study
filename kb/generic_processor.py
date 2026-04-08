"""
通用文件导入处理器

处理本地文件和文件夹：
- PDF（含扫描件检测和 OCR）
- Office 文档（Word, Excel, PPTX）
- Markdown 和纯文本
- 目录递归扫描
- 增量导入和断点续传
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from llama_index.core.schema import Document as LlamaDocument
from llamaindex_study.node_parser import get_node_parser

from kb.document_processor import (
    DocumentProcessor,
    DocumentProcessorConfig,
    ProcessingProgress,
)


@dataclass
class FileImportConfig:
    """文件导入配置"""

    source_name: str = "generic"  # 数据源名称
    source_paths: List[Path] = field(default_factory=list)  # 数据源目录
    exclude_patterns: List[str] = field(
        default_factory=lambda: ["*.xls", "*.xlsx", ".DS_Store"]
    )
    chunk_size: int = 512
    chunk_overlap: int = 50
    batch_size: int = 50


class GenericImporter:
    """
    通用文件导入器

    功能：
    - 多目录扫描
    - PDF 扫描件检测和 OCR
    - Office 文档处理
    - 增量导入和断点续传
    - 进度保存
    """

    def __init__(
        self,
        config: Optional[FileImportConfig] = None,
        processor_config: Optional[DocumentProcessorConfig] = None,
        kb_id: Optional[str] = None,
        persist_dir: Optional[Path] = None,
    ):
        self.config = config or FileImportConfig()
        self.processor = DocumentProcessor(
            config=processor_config
            or DocumentProcessorConfig(
                chunk_size=self.config.chunk_size,
                chunk_overlap=self.config.chunk_overlap,
                batch_size=self.config.batch_size,
            )
        )
        self.kb_id = kb_id
        self.persist_dir = persist_dir
        self._dedup_manager = None

    def _init_dedup_manager(self, vector_store=None):
        if self._dedup_manager or not self.kb_id or not self.persist_dir:
            return
        from kb.deduplication import DeduplicationManager

        uri = str(self.persist_dir)
        if vector_store is not None:
            try:
                uri = vector_store._get_lance_vector_store().uri
            except Exception:
                pass
        self._dedup_manager = DeduplicationManager(
            kb_id=self.kb_id,
            persist_dir=self.persist_dir,
            uri=uri,
            table_name=self.kb_id,
        )

    def set_dedup_manager(self, manager):
        self._dedup_manager = manager

    def collect_files(
        self,
        directories: List[Path] = None,
        exclude_patterns: List[str] = None,
        recursive: bool = True,
        include_exts: List[str] = None,
        exclude_exts: List[str] = None,
    ) -> List[Path]:
        """
        收集所有支持的文件

        Args:
            directories: 目录列表（默认使用配置中的目录）
            exclude_patterns: 排除模式
            recursive: 是否递归
            include_exts: 只包含指定的扩展名列表 (如 ["pdf", "md"])，覆盖默认
            exclude_exts: 从默认列表中排除的扩展名列表 (如 ["xlsx", "png"])

        Returns:
            文件路径列表
        """
        directories = directories or self.config.source_paths
        exclude_patterns = exclude_patterns or self.config.exclude_patterns

        files = []
        image_exts = {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".bmp",
            ".svg",
            ".webp",
            ".ico",
            ".tiff",
            ".tif",
            ".heic",
            ".avif",
        }

        # 默认支持的扩展名 (包含表格格式 xlsx, xls)
        default_supported_exts = {
            ".pdf",
            ".docx",
            ".doc",
            ".xlsx",
            ".xls",
            ".pptx",
            ".md",
            ".txt",
            ".html",
            ".htm",
        }

        # 确定最终使用的支持扩展名
        if include_exts:
            # include 覆盖默认：只处理指定的扩展名
            supported_exts = {f".{ext.lstrip('.')}" for ext in include_exts}
        else:
            # 默认使用全部支持的扩展名
            supported_exts = default_supported_exts.copy()

        # exclude 从支持列表中排除
        if exclude_exts:
            for ext in exclude_exts:
                clean_ext = f".{ext.lstrip('.')}"
                supported_exts.discard(clean_ext)

        for directory in directories:
            if not directory.exists():
                print(f"   ⚠️  目录不存在: {directory}")
                continue

            pattern = "**/*" if recursive else "*"

            for file_path in directory.glob(pattern):
                if not file_path.is_file():
                    continue

                ext = file_path.suffix.lower()

                # 排除图片文件 (始终排除，不受 include/exclude 影响)
                if ext in image_exts:
                    continue

                # 排除隐藏文件
                if file_path.name.startswith("."):
                    continue

                # 排除无扩展名或不在支持列表的文件
                if not ext or ext not in supported_exts:
                    continue

                # 检查排除模式
                if any(file_path.match(p) for p in exclude_patterns):
                    continue

                # 检查文件大小
                if file_path.stat().st_size == 0:
                    continue

                if file_path.stat().st_size > 100 * 1024 * 1024:  # 100MB
                    print(f"   ⏭️  跳过过大文件: {file_path.name}")
                    continue

                files.append(file_path)

        return files

    def import_files(
        self,
        file_paths: List[Path],
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        if progress:
            progress.total_items = len(file_paths)
            if not progress.started_at:
                progress.started_at = time.time()

        self._init_dedup_manager(vector_store)
        self.processor.set_embed_model(embed_model)
        node_parser = get_node_parser(
            chunk_size=self.processor.config.chunk_size,
            chunk_overlap=self.processor.config.chunk_overlap,
        )

        processed_set = set(progress.processed_items) if progress else set()

        stats = {"files": 0, "nodes": 0, "failed": 0, "skipped": 0}

        for i, file_path in enumerate(file_paths):
            path_str = str(file_path)
            if path_str in processed_set:
                continue

            # 增量更新：检查文件是否已修改
            if self.processor.config.incremental and progress:
                if not self.processor.is_file_changed(path_str, progress):
                    stats["skipped"] += 1
                    continue

                # 更新文件哈希
                file_hash = self.processor.compute_file_hash(path_str)
                if progress:
                    progress.file_hashes[path_str] = file_hash

            if i % 10 == 0:
                elapsed = time.time() - (
                    progress.started_at if progress else time.time()
                )
                print(
                    f"\n   进度: {i + 1}/{len(file_paths)} ({100 * (i + 1) // len(file_paths)}%)"
                )
                print(
                    f"   节点: {stats['nodes']}, 跳过: {stats['skipped']}, 耗时: {elapsed:.0f}s"
                )

            if on_progress:
                on_progress(i + 1, len(file_paths), file_path.name)

            # 准备元数据
            metadata = {
                "source": self.config.source_name,
                "file_path": str(file_path),
                "file_name": file_path.name,
                "file_ext": file_path.suffix.lower(),
                "file_size": file_path.stat().st_size,
            }

            try:
                # 处理文件
                docs = self.processor.process_file(str(file_path), metadata=metadata)

                if docs:
                    import hashlib

                    all_nodes = []
                    doc_id_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:16]

                    for doc in docs:
                        doc.id_ = f"doc_{doc_id_hash}"
                        nodes = node_parser.get_nodes_from_documents([doc])
                        saved = self.processor.save_nodes(vector_store, nodes, progress)
                        stats["nodes"] += saved
                        stats["files"] += 1
                        all_nodes.extend(nodes)

                    # 更新去重状态并创建 document/chunk 记录
                    if self._dedup_manager and all_nodes:
                        try:
                            content = file_path.read_text(
                                encoding="utf-8", errors="ignore"
                            )
                            doc_id = f"doc_{doc_id_hash}"
                            self._dedup_manager.mark_processed(
                                file_path,
                                content,
                                doc_id,
                                chunk_count=len(all_nodes),
                                nodes=all_nodes,
                            )
                        except Exception as e:
                            print(f"   ⚠️  更新去重状态失败: {e}")

                    if progress:
                        progress.processed_items.append(path_str)
                else:
                    stats["failed"] += 1

            except Exception as e:
                print(f"   ⚠️  处理失败: {file_path.name} - {e}")
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(path_str)

        # 保存去重状态
        if self._dedup_manager:
            self._dedup_manager._save()

        return stats

    def import_directory(
        self,
        directory: Path,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        rebuild: bool = False,
        exclude_patterns: List[str] = None,
        recursive: bool = True,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """
        导入整个目录

        Args:
            directory: 目录路径
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录
            rebuild: 是否重建
            exclude_patterns: 排除模式
            recursive: 是否递归
            on_progress: 进度回调

        Returns:
            导入统计
        """
        print(f"\n{'=' * 60}")
        print(f"📁 {self.config.source_name}: {directory}")
        print(f"{'=' * 60}")

        # 收集文件
        files = self.collect_files([directory], exclude_patterns, recursive)
        print(f"   找到 {len(files)} 个文件")

        if not files:
            return {"files": 0, "nodes": 0, "failed": 0}

        return self.import_files(
            files, vector_store, embed_model, progress, on_progress
        )

    def process_file(
        self,
        path: Path,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
    ) -> dict:
        """导入单个文件"""
        return self.import_files(
            file_paths=[path],
            vector_store=vector_store,
            embed_model=embed_model,
            progress=progress,
        )

    def import_paths(
        self,
        paths: List[str],
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        rebuild: bool = False,
        exclude_patterns: List[str] = None,
        recursive: bool = True,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """
        从路径列表导入（文件和目录混合）

        Args:
            paths: 路径字符串列表
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录
            rebuild: 是否重建
            exclude_patterns: 排除模式
            recursive: 是否递归
            on_progress: 进度回调

        Returns:
            导入统计
        """
        print(f"\n{'=' * 60}")
        print(f"📦 {self.config.source_name}: 批量导入")
        print(f"{'=' * 60}")

        # 分离文件和目录
        all_files = []
        directories = []

        for path_str in paths:
            path = Path(path_str)
            if not path.exists():
                print(f"   ⚠️  路径不存在: {path_str}")
                continue

            if path.is_file():
                all_files.append(path)
            elif path.is_dir():
                directories.append(path)
                # 收集目录中的文件
                files = self.collect_files([path], exclude_patterns, recursive)
                all_files.extend(files)

        print(f"   找到 {len(all_files)} 个文件")

        if not all_files:
            return {"files": 0, "nodes": 0, "failed": 0}

        return self.import_files(
            all_files, vector_store, embed_model, progress, on_progress
        )
