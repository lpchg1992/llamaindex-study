"""
配置管理模块

负责从 .env 文件加载配置，提供统一的配置访问接口。
支持：
  - LLM：硅基流动（SiliconFlow，OpenAI 兼容格式）
  - Embedding：本地 Ollama（bge-m3）
"""

import os
from pathlib import Path
from typing import ClassVar, List, Optional

from dotenv import load_dotenv

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings:
    """
    应用程序配置类

    提供类型安全的配置访问接口，自动从环境变量加载配置。
    """

    # 类级别的环境变量默认值
    _DEFAULT_SILICONFLOW_BASE_URL: ClassVar[str] = "https://api.siliconflow.cn/v1"
    _DEFAULT_SILICONFLOW_MODEL: ClassVar[str] = "Pro/deepseek-ai/DeepSeek-V3.2"
    _DEFAULT_OLLAMA_BASE_URL: ClassVar[str] = "http://localhost:11434"
    _DEFAULT_OLLAMA_EMBED_MODEL: ClassVar[str] = "bge-m3"
    _DEFAULT_OLLAMA_REMOTE_URL: ClassVar[str] = ""
    _DEFAULT_PERSIST_DIR: ClassVar[str] = str(PROJECT_ROOT / ".llamaindex" / "storage")
    _DEFAULT_ZOTERO_PERSIST_DIR: ClassVar[str] = str(
        PROJECT_ROOT / ".llamaindex" / "storage" / "zotero"
    )
    _DEFAULT_DATA_DIR: ClassVar[str] = str(Path.home() / ".llamaindex")
    _DEFAULT_TOP_K: ClassVar[int] = 5
    _DEFAULT_RERANK_MODEL: ClassVar[str] = "Pro/BAAI/bge-reranker-v2-m3"
    _DEFAULT_USE_RERANKER: ClassVar[bool] = False
    _DEFAULT_VECTOR_STORE_TYPE: ClassVar[str] = "lancedb"
    _DEFAULT_VECTOR_TABLE_NAME: ClassVar[str] = "llamaindex"
    _DEFAULT_QDRANT_URL: ClassVar[str] = "http://localhost:6333"

    def __init__(self) -> None:
        """初始化配置，从环境变量加载所有配置项"""
        # 加载 .env 文件
        env_path: Path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        # ========== LLM 配置（硅基流动）==========
        self.siliconflow_base_url: str = os.getenv(
            "SILICONFLOW_BASE_URL", self._DEFAULT_SILICONFLOW_BASE_URL
        )
        self.siliconflow_api_key: Optional[str] = os.getenv("SILICONFLOW_API_KEY")
        self.siliconflow_model: str = os.getenv(
            "SILICONFLOW_MODEL", self._DEFAULT_SILICONFLOW_MODEL
        )

        # ========== Embedding 配置（Ollama 多端点）==========
        base_url = os.getenv("OLLAMA_BASE_URL")
        self.ollama_local_url: str = os.getenv(
            "OLLAMA_LOCAL_URL",
            base_url or self._DEFAULT_OLLAMA_BASE_URL,
        )
        self.ollama_remote_url: str = os.getenv(
            "OLLAMA_REMOTE_URL",
            self._DEFAULT_OLLAMA_REMOTE_URL,
        ).strip()
        self.ollama_base_url: str = base_url or self.ollama_local_url
        self.ollama_embed_model: str = os.getenv(
            "OLLAMA_EMBED_MODEL", self._DEFAULT_OLLAMA_EMBED_MODEL
        )
        self.ollama_max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
        self.ollama_retry_delay: float = float(os.getenv("RETRY_DELAY", "1.0"))
        self.ollama_short_text_threshold: int = int(
            os.getenv("OLLAMA_SHORT_TEXT_THRESHOLD", "600")
        )
        self.ollama_fanout_text_threshold: int = int(
            os.getenv("OLLAMA_FANOUT_TEXT_THRESHOLD", "1800")
        )

        # ========== 索引配置 ==========
        self.persist_dir: str = self._resolve_dir(
            os.getenv("PERSIST_DIR", self._DEFAULT_PERSIST_DIR),
            self._DEFAULT_PERSIST_DIR,
        )

        # Zotero 向量数据存储目录
        self.zotero_persist_dir: str = self._resolve_dir(
            os.getenv("ZOTERO_PERSIST_DIR", self._DEFAULT_ZOTERO_PERSIST_DIR),
            self._DEFAULT_ZOTERO_PERSIST_DIR,
        )

        # 任务队列数据目录
        self.data_dir: str = self._resolve_dir(
            os.getenv("DATA_DIR", self._DEFAULT_DATA_DIR),
            self._DEFAULT_DATA_DIR,
        )

        # ========== 检索配置 ==========
        self.top_k: int = int(os.getenv("TOP_K", str(self._DEFAULT_TOP_K)))
        self.use_semantic_chunking: bool = (
            os.getenv("USE_SEMANTIC_CHUNKING", "false").lower() == "true"
        )
        self.use_auto_merging: bool = (
            os.getenv("USE_AUTO_MERGING", "false").lower() == "true"
        )
        self.use_hybrid_search: bool = (
            os.getenv("USE_HYBRID_SEARCH", "false").lower() == "true"
        )
        self.hybrid_search_alpha: float = float(os.getenv("HYBRID_SEARCH_ALPHA", "0.5"))
        self.hybrid_search_mode: str = os.getenv("HYBRID_SEARCH_MODE", "relative_score")
        self.chunk_size: int = int(os.getenv("CHUNK_SIZE", "512"))
        self.chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "50"))
        self.embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))

        # ========== 分块策略配置 ==========
        self.chunk_strategy: str = os.getenv("CHUNK_STRATEGY", "hierarchical")
        self.hierarchical_chunk_sizes: List[int] = [
            int(x)
            for x in os.getenv("HIERARCHICAL_CHUNK_SIZES", "2048,512,128").split(",")
        ]
        self.sentence_chunk_size: int = int(os.getenv("SENTENCE_CHUNK_SIZE", "512"))
        self.sentence_chunk_overlap: int = int(
            os.getenv("SENTENCE_CHUNK_OVERLAP", "50")
        )

        # ========== Query Transform 配置 ==========
        self.use_hyde: bool = os.getenv("USE_HYDE", "false").lower() == "true"
        self.use_query_rewrite: bool = (
            os.getenv("USE_QUERY_REWRITE", "false").lower() == "true"
        )
        self.use_multi_query: bool = (
            os.getenv("USE_MULTI_QUERY", "false").lower() == "true"
        )

        # ========== Response Synthesizer 配置 ==========
        self.response_mode: str = os.getenv("RESPONSE_MODE", "compact")

        # ========== Reranker 配置 ==========
        self.rerank_model: str = os.getenv("RERANK_MODEL", self._DEFAULT_RERANK_MODEL)
        self.use_reranker: bool = os.getenv("USE_RERANKER", "true").lower() == "true"

        # ========== 向量数据库配置 ==========
        self.vector_store_type: str = os.getenv(
            "VECTOR_STORE_TYPE", self._DEFAULT_VECTOR_STORE_TYPE
        )
        self.vector_db_uri: str = os.getenv("VECTOR_DB_URI", "")
        self.vector_table_name: str = os.getenv(
            "VECTOR_TABLE_NAME", self._DEFAULT_VECTOR_TABLE_NAME
        )

        # Qdrant 专用配置
        self.qdrant_url: str = os.getenv("QDRANT_URL", self._DEFAULT_QDRANT_URL)
        self.qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")

        # Doc2x 配置
        self.doc2x_api_key: Optional[str] = os.getenv("DOC2X_API_KEY")

        # MinerU 配置
        self.mineru_api_key: Optional[str] = os.getenv("MINERU_API_KEY")
        self.mineru_pipeline_id: Optional[str] = os.getenv("MINERU_PIPELINE_ID")

    def __repr__(self) -> str:
        """返回配置的字符串表示"""
        return (
            f"Settings("
            f"llm=siliconflow:{self.siliconflow_model}, "
            f"embed=ollama:{self.ollama_embed_model}, "
            f"top_k={self.top_k})"
        )

    def get_ollama_endpoints(self) -> list[tuple[str, str]]:
        """返回去重后的 Ollama 端点列表"""
        endpoints = [("本地", self.ollama_local_url)]
        if self.ollama_remote_url:
            endpoints.append(("远程", self.ollama_remote_url))

        unique_endpoints: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        for name, url in endpoints:
            normalized_url = url.strip()
            if not normalized_url or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            unique_endpoints.append((name, normalized_url))

        return unique_endpoints

    def _resolve_dir(self, configured_dir: str, fallback_dir: str) -> str:
        candidate = Path(configured_dir).expanduser()
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return str(candidate)
        except OSError as exc:
            fallback = Path(fallback_dir).expanduser()
            fallback.mkdir(parents=True, exist_ok=True)
            logger.warning(
                f"目录不可写，回退到本地目录: {candidate} -> {fallback} ({exc})"
            )
            return str(fallback)


# 全局配置实例（延迟加载）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    获取全局配置实例（单例模式）

    Returns:
        Settings: 配置实例
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
