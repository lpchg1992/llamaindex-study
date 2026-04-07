"""
LlamaIndex Study
"""

__version__ = "0.1.0"
__author__ = "lpchg1992"

from llamaindex_study.config import Settings, get_settings
from llamaindex_study.logger import (
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
from llamaindex_study.ollama_utils import (
    create_ollama_embedding,
    configure_global_embed_model,
    configure_embed_model_by_model_id,
    configure_llamaindex_for_siliconflow,
    BatchEmbeddingHelper,
)
from llamaindex_study.embedding_service import (
    OllamaEmbeddingService,
    OllamaEndpoint,
    get_embedding_service,
    reset_embedding_service,
)
from llamaindex_study.reader import (
    DocumentReader,
    SmartDocumentProcessor,
    load_and_split,
)
from llamaindex_study.index_builder import IndexBuilder
from llamaindex_study.query_engine import QueryEngineWrapper, create_query_engine
from llamaindex_study.vector_store import (
    VectorStoreType,
    LanceDBVectorStore,
    ChromaVectorStore,
    QdrantVectorStore,
    create_vector_store,
    get_default_vector_store,
)
from llamaindex_study.callbacks import (
    setup_callbacks,
    get_callback_manager,
    get_token_counter,
    get_rag_stats,
    reset_callbacks,
)
from llamaindex_study.chat_engine import (
    ChatService,
    ChatStore,
    get_chat_service,
)
from llamaindex_study.structured_extractor import (
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
    "configure_llamaindex_for_siliconflow",
    "BatchEmbeddingHelper",
    "OllamaEmbeddingService",
    "OllamaEndpoint",
    "get_embedding_service",
    "reset_embedding_service",
    "DocumentReader",
    "SmartDocumentProcessor",
    "load_and_split",
    "IndexBuilder",
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
