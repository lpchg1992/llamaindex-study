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

class GenericService:
    """通用文件导入服务"""

    @staticmethod
    def import_file(
        kb_id: str,
        path: str,
        refresh_topics: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
        chunk_strategy: Optional[str] = None,
        chunk_size: Optional[int] = None,
        hierarchical_chunk_sizes: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        """
        导入单个文件

        Args:
            kb_id: 知识库 ID
            path: 文件路径
            progress_callback: 进度回调
            chunk_strategy: 分块策略
            chunk_size: 分块大小
            hierarchical_chunk_sizes: 层级分块大小列表

        Returns:
            导入统计
        """
        from kb_processing.generic_processor import GenericImporter
        from kb_processing.document_processor import DocumentProcessorConfig

        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"文件不存在: {path}")

        vs = VectorStoreService.get_vector_store(kb_id)
        persist_dir = VectorStoreService.get_persist_dir(kb_id)

        settings = get_settings()
        config = DocumentProcessorConfig(
            chunk_size=chunk_size or settings.chunk_size,
            chunk_strategy=chunk_strategy or settings.chunk_strategy,
            hierarchical_chunk_sizes=hierarchical_chunk_sizes or settings.hierarchical_chunk_sizes,
        )
        importer = GenericImporter(kb_id=kb_id, persist_dir=persist_dir, processor_config=config)

        if progress_callback:
            progress_callback(f"开始导入: {file_path.name}")

        try:
            stats = importer.process_file(
                path=file_path,
                vector_store=vs,
                embed_model=create_parallel_ollama_embedding(),
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

        except Exception as e:
            if progress_callback:
                progress_callback(f"导入失败: {e}")
            raise

# =============================================================================
