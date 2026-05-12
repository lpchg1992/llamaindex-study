"""
LlamaIndex Study

基于 LlamaIndex 的现代化 RAG 应用核心库，提供：
- 配置管理 (Settings, get_settings)
- 日志工具 (get_logger, get_app_logger, etc.)
- Embedding 服务 (create_ollama_embedding)
- 文档处理 (DocumentReader, SmartDocumentProcessor, load_and_split)
- 查询引擎 (QueryEngineWrapper, create_query_engine)
- 向量存储 (LanceDBVectorStore)
- 回调和可观测性 (setup_callbacks, get_token_counter, get_rag_stats)
- 聊天服务 (ChatService, ChatStore)

用法:
    from llamaindex_study import get_settings, get_logger, QueryEngineWrapper
"""

__version__ = "0.1.0"
__author__ = "lpchg1992"

from rag.config import Settings, get_settings
from rag.logger import (
    get_logger,
    get_app_logger,
    get_kb_logger,
    get_api_logger,
    get_task_log_file,
    setup_task_logger,
    configure_all_loggers,
    get_log_dir,
    set_log_dir,
)
from rag.embedding_factory import (
    create_ollama_embedding,
    configure_global_embed_model,
    configure_embed_model_by_model_id,
)
from rag.reader import (
    DocumentReader,
    SmartDocumentProcessor,
    load_and_split,
)
from rag.query_engine import QueryEngineWrapper, create_query_engine
from rag.vector_store import (
    LanceDBVectorStore,
    get_default_vector_store,
)
from rag.callbacks import (
    setup_callbacks,
    get_callback_manager,
    get_token_counter,
    get_rag_stats,
    reset_callbacks,
)
from rag.chat_engine import (
    ChatService,
    ChatStore,
    get_chat_service,
)

# Optional new modules — import failures must not block application startup
try:
    from rag.ingestion import (
        TextCleanerTransform,
        ContextEnricherTransform,
        ReferenceDetectorTransform,
        create_ingestion_pipeline,
        run_ingestion_pipeline,
        build_nodes_with_pipeline,
    )
except ImportError:
    TextCleanerTransform = None
    ContextEnricherTransform = None  # type: ignore[assignment]
    ReferenceDetectorTransform = None  # type: ignore[assignment]
    create_ingestion_pipeline = None  # type: ignore[assignment]
    run_ingestion_pipeline = None  # type: ignore[assignment]
    build_nodes_with_pipeline = None  # type: ignore[assignment]

try:
    from rag.metadata_extractors import (
        create_metadata_extractors,
    )
except ImportError:
    create_metadata_extractors = None  # type: ignore[assignment]

try:
    from rag.evaluation import (
        evaluate_faithfulness,
        evaluate_relevancy,
        evaluate_correctness,
        evaluate_full,
        run_batch_evaluation,
    )
except ImportError:
    evaluate_faithfulness = None  # type: ignore[assignment]
    evaluate_relevancy = None  # type: ignore[assignment]
    evaluate_correctness = None  # type: ignore[assignment]
    evaluate_full = None  # type: ignore[assignment]
    run_batch_evaluation = None  # type: ignore[assignment]

# Build __all__ dynamically, excluding any symbol that failed to import
_core_exports = [
    "Settings",
    "get_settings",
    "get_logger",
    "get_app_logger",
    "get_kb_logger",
    "get_api_logger",
    "get_task_log_file",
    "setup_task_logger",
    "configure_all_loggers",
    "get_log_dir",
    "set_log_dir",
    "create_ollama_embedding",
    "configure_global_embed_model",
    "configure_embed_model_by_model_id",
    "DocumentReader",
    "SmartDocumentProcessor",
    "load_and_split",
    "QueryEngineWrapper",
    "create_query_engine",
    "LanceDBVectorStore",
    "get_default_vector_store",
    "setup_callbacks",
    "get_callback_manager",
    "get_token_counter",
    "get_rag_stats",
    "reset_callbacks",
    "ChatService",
    "ChatStore",
    "get_chat_service",
]
_optional_exports = [
    "TextCleanerTransform",
    "ContextEnricherTransform",
    "ReferenceDetectorTransform",
    "create_ingestion_pipeline",
    "run_ingestion_pipeline",
    "build_nodes_with_pipeline",
    "create_metadata_extractors",
    "evaluate_faithfulness",
    "evaluate_relevancy",
    "evaluate_correctness",
    "evaluate_full",
    "run_batch_evaluation",
]
__all__ = _core_exports + [
    name for name in _optional_exports
    if globals().get(name) is not None
]


