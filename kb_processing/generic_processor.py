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

from .document_processor import (
    DocumentProcessor,
    DocumentProcessorConfig,
    ProcessingProgress,
)
from kb_core.document_chunk_service import get_document_chunk_service


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
        """Import a list of files with incremental update support.

        Checks file hashes against the document table to skip unchanged files.
        Embeds and persists nodes via the vector store and document service.

        Args:
            file_paths: List of file paths to import
            vector_store: LanceDB vector store instance
            embed_model: Embedding model for vectorization
            progress: Optional progress tracker (mutated in place)
            on_progress: Optional callback(current, total, filename)

        Returns:
            Dict with counts of files, nodes, failed, and skipped
        """
        if progress:
            progress.total_items = len(file_paths)
            if not progress.started_at:
                progress.started_at = time.time()

        self.processor.set_embed_model(embed_model)
        node_parser = self.processor.get_node_parser()

        processed_set = set(progress.processed_items) if progress else set()

        stats = {"files": 0, "nodes": 0, "failed": 0, "skipped": 0}

        for i, file_path in enumerate(file_paths):
            path_str = str(file_path)
            if path_str in processed_set:
                continue

            # 增量更新：基于 Document 表检查文件是否已修改
            from kb_core.database import init_document_db

            doc_db = init_document_db()
            existing = doc_db.get_by_source_path(self.kb_id, path_str)
            if existing:
                current_hash = self.processor.compute_file_hash(path_str)
                if existing.get("file_hash") == current_hash:
                    stats["skipped"] += 1
                    continue

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
                    all_failed_ids = []

                    for doc in docs:
                        doc.id_ = f"doc_{doc_id_hash}"
                        nodes = node_parser.get_nodes_from_documents([doc])

                        # Generate embeddings inline (same pattern as _execute_generic)
                        if nodes:
                            texts = [node.get_content() for node in nodes]
                            failed_node_ids = []
                            for j, text in enumerate(texts):
                                try:
                                    ep = embed_model._get_best_endpoint()
                                    ep_name, embedding, error = embed_model._get_embedding_with_retry(text, ep)
                                    if error:
                                        failed_node_ids.append(nodes[j].node_id)
                                    elif all(v == 0.0 for v in embedding):
                                        failed_node_ids.append(nodes[j].node_id)
                                    else:
                                        nodes[j].embedding = embedding
                                except Exception as emb_err:
                                    print(f"      ⚠️  Embedding 失败: {emb_err}")
                                    failed_node_ids.append(nodes[j].node_id)

                            all_failed_ids.extend(failed_node_ids)
                            all_nodes.extend(nodes)

                    if not all_nodes:
                        stats["failed"] += 1
                        continue

                    doc_id = f"doc_{doc_id_hash}"

                    # Write to SQLite FIRST (correct order)
                    try:
                        doc_chunk_service = get_document_chunk_service(self.kb_id)
                        file_hash = self.processor.compute_file_hash(str(file_path))
                        result = doc_chunk_service.create_document(
                            source_file=file_path.name,
                            source_path=str(file_path),
                            file_hash=file_hash,
                            nodes=all_nodes,
                            file_size=file_path.stat().st_size,
                            doc_id=doc_id,
                            failed_node_ids=all_failed_ids if all_failed_ids else None,
                        )
                        if not result:
                            print(f"   ⚠️  SQLite 文档记录创建失败: {file_path}")
                            continue
                    except Exception as e:
                        print(f"   ⚠️  写入 Document 记录失败: {e}")
                        continue

                    # Then write to LanceDB (correct order)
                    try:
                        lance_store = vector_store._get_lance_vector_store()
                        success_count, skipped, emb_failed_ids = self.processor._upsert_nodes(lance_store, all_nodes)
                        if emb_failed_ids:
                            doc_chunk_service.mark_chunks_failed(emb_failed_ids)
                            all_failed_ids.extend(emb_failed_ids)
                        stats["nodes"] += success_count
                        stats["files"] += 1
                    except Exception as write_ex:
                        print(f"   ⚠️  LanceDB 写入失败（SQLite 已保存）: {file_path}, 错误: {write_ex}")
                        node_ids = [n.node_id for n in all_nodes]
                        doc_chunk_service.mark_chunks_failed(node_ids)
                        continue

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
        """Import a single file (wrapper around import_files).

        Args:
            path: File path to import
            vector_store: LanceDB vector store instance
            embed_model: Embedding model for vectorization
            progress: Optional progress tracker

        Returns:
            Dict with counts of files, nodes, failed, and skipped
        """
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
