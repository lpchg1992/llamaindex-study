"""
LlamaIndex Study

基于 LlamaIndex 的现代化 RAG 应用核心库，提供：
- 配置管理 (Settings, get_settings)
- 日志工具 (get_logger, get_app_logger, etc.)
- Embedding 服务 (OllamaEmbeddingService, create_ollama_embedding)
- 文档处理 (DocumentReader, SmartDocumentProcessor, load_and_split)
- 查询引擎 (QueryEngineWrapper, create_query_engine)
- 向量存储 (LanceDBVectorStore, ChromaVectorStore, QdrantVectorStore)
- 回调和可观测性 (setup_callbacks, get_token_counter, get_rag_stats)
- 聊天服务 (ChatService, ChatStore)
- 结构化提取 (StructuredExtractor, PydanticProgram)

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
from rag.ollama_utils import (
    create_ollama_embedding,
    configure_global_embed_model,
    configure_embed_model_by_model_id,
    BatchEmbeddingHelper,
)
from rag.embedding_service import (
    OllamaEmbeddingService,
    OllamaEndpoint,
    get_embedding_service,
    reset_embedding_service,
)
from rag.reader import (
    DocumentReader,
    SmartDocumentProcessor,
    load_and_split,
)
from rag.query_engine import QueryEngineWrapper, create_query_engine
from rag.vector_store import (
    VectorStoreType,
    LanceDBVectorStore,
    ChromaVectorStore,
    QdrantVectorStore,
    create_vector_store,
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
from rag.structured_extractor import (
    StructuredExtractor,
    PydanticProgram,
    TextToJsonExtractor,
    get_extractor,
)

__all__ = [
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
    "BatchEmbeddingHelper",
    "OllamaEmbeddingService",
    "OllamaEndpoint",
    "get_embedding_service",
    "reset_embedding_service",
    "DocumentReader",
    "SmartDocumentProcessor",
    "load_and_split",
    "QueryEngineWrapper",
    "create_query_engine",
    "VectorStoreType",
    "LanceDBVectorStore",
    "ChromaVectorStore",
    "QdrantVectorStore",
    "create_vector_store",
    "get_default_vector_store",
    "setup_callbacks",
    "get_callback_manager",
    "get_token_counter",
    "get_rag_stats",
    "reset_callbacks",
    "ChatService",
    "ChatStore",
    "get_chat_service",
    "StructuredExtractor",
    "PydanticProgram",
    "TextToJsonExtractor",
    "get_extractor",
]
