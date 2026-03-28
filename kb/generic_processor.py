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
from typing import List, Optional

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument

from kb.document_processor import DocumentProcessor, DocumentProcessorConfig, ProcessingProgress


@dataclass
class FileImportConfig:
    """文件导入配置"""
    source_name: str = "generic"  # 数据源名称
    source_paths: List[Path] = field(default_factory=list)  # 数据源目录
    exclude_patterns: List[str] = field(default_factory=lambda: ["*.xls", "*.xlsx", ".DS_Store"])
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
    ):
        """
        初始化通用导入器
        """
        self.config = config or FileImportConfig()
        self.processor = DocumentProcessor(config=processor_config or DocumentProcessorConfig(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            batch_size=self.config.batch_size,
        ))

    def collect_files(
        self,
        directories: List[Path] = None,
        exclude_patterns: List[str] = None,
        recursive: bool = True,
    ) -> List[Path]:
        """
        收集所有支持的文件

        Args:
            directories: 目录列表（默认使用配置中的目录）
            exclude_patterns: 排除模式
            recursive: 是否递归

        Returns:
            文件路径列表
        """
        directories = directories or self.config.source_paths
        exclude_patterns = exclude_patterns or self.config.exclude_patterns

        files = []
        exclude_exts = {".xls", ".xlsx"}

        for directory in directories:
            if not directory.exists():
                print(f"   ⚠️  目录不存在: {directory}")
                continue

            pattern = "**/*" if recursive else "*"

            for file_path in directory.glob(pattern):
                if not file_path.is_file():
                    continue

                # 排除特定扩展名
                if file_path.suffix.lower() in exclude_exts:
                    continue

                # 排除隐藏文件
                if file_path.name.startswith('.'):
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
        on_progress: Optional[callable] = None,
    ) -> dict:
        """
        导入文件列表

        Args:
            file_paths: 文件路径列表
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录
            on_progress: 进度回调

        Returns:
            导入统计
        """
        if progress:
            progress.total_items = len(file_paths)
            if not progress.started_at:
                progress.started_at = time.time()

        self.processor.set_embed_model(embed_model)
        node_parser = SentenceSplitter(
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
                elapsed = time.time() - (progress.started_at if progress else time.time())
                print(f"\n   进度: {i+1}/{len(file_paths)} ({100*(i+1)//len(file_paths)}%)")
                print(f"   节点: {stats['nodes']}, 跳过: {stats['skipped']}, 耗时: {elapsed:.0f}s")

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
                    for doc in docs:
                        nodes = node_parser.get_nodes_from_documents([doc])
                        saved = self.processor.save_nodes(vector_store, nodes, progress)
                        stats["nodes"] += saved
                        stats["files"] += 1

                    if progress:
                        progress.processed_items.append(path_str)
                else:
                    stats["failed"] += 1

            except Exception as e:
                print(f"   ⚠️  处理失败: {file_path.name} - {e}")
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(path_str)

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
        on_progress: Optional[callable] = None,
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
        print(f"\n{'='*60}")
        print(f"📁 {self.config.source_name}: {directory}")
        print(f"{'='*60}")

        # 收集文件
        files = self.collect_files([directory], exclude_patterns, recursive)
        print(f"   找到 {len(files)} 个文件")

        if not files:
            return {"files": 0, "nodes": 0, "failed": 0}

        return self.import_files(files, vector_store, embed_model, progress, on_progress)

    def import_paths(
        self,
        paths: List[str],
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        rebuild: bool = False,
        exclude_patterns: List[str] = None,
        recursive: bool = True,
        on_progress: Optional[callable] = None,
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
        print(f"\n{'='*60}")
        print(f"📦 {self.config.source_name}: 批量导入")
        print(f"{'='*60}")

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

        return self.import_files(all_files, vector_store, embed_model, progress, on_progress)
