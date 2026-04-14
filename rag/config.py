"""
配置管理模块

负责从 .env 文件加载配置，提供统一的配置访问接口。
支持：
  - LLM：硅基流动（SiliconFlow，OpenAI 兼容格式）
  - Embedding：本地 Ollama（bge-m3）

运行时设置持久化：
  - 运行时可更改的设置（top_k, use_hybrid_search 等）保存到 .runtime_settings.json
  - LLM/Embedding 设置保存到 .env 文件
  - default_llm_model 通过模型数据库的 is_default 字段管理
"""

import json
import os
from pathlib import Path
from typing import ClassVar, List, Optional

from dotenv import load_dotenv

from rag.logger import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RUNTIME_SETTINGS_FILE = PROJECT_ROOT / ".runtime_settings.json"


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
    _DEFAULT_OLLAMA_LLM_MODEL: ClassVar[str] = "tomng/lfm2.5-instruct:1.2b"
    _DEFAULT_LLM_MODE: ClassVar[str] = "ollama"
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

        # ========== LLM 模式选择 ==========
        self.llm_mode: str = os.getenv("LLM_MODE", self._DEFAULT_LLM_MODE)
        self.ollama_llm_model: str = os.getenv(
            "OLLAMA_LLM_MODEL", self._DEFAULT_OLLAMA_LLM_MODEL
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
        self.ollama_max_retries: int = int(os.getenv("MAX_RETRIES", "5"))
        self.ollama_retry_delay: float = float(os.getenv("RETRY_DELAY", "2.0"))
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
        self.chunk_size: int = int(os.getenv("CHUNK_SIZE", "1024"))
        self.chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))
        self.embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))

        # ========== 分块策略配置 ==========
        self.chunk_strategy: str = os.getenv("CHUNK_STRATEGY", "hierarchical")
        self.hierarchical_chunk_sizes: List[int] = [
            int(x)
            for x in os.getenv("HIERARCHICAL_CHUNK_SIZES", "2048,1024,512").split(",")
        ]
        self.sentence_chunk_size: int = int(os.getenv("SENTENCE_CHUNK_SIZE", "1024"))
        self.sentence_chunk_overlap: int = int(
            os.getenv("SENTENCE_CHUNK_OVERLAP", "100")
        )

        # ========== Query Transform 配置 ==========
        self.use_hyde: bool = os.getenv("USE_HYDE", "false").lower() == "true"
        self.use_query_rewrite: bool = (
            os.getenv("USE_QUERY_REWRITE", "false").lower() == "true"
        )
        self.use_multi_query: bool = (
            os.getenv("USE_MULTI_QUERY", "false").lower() == "true"
        )
        self.num_multi_queries: int = int(os.getenv("MULTI_QUERY_NUM", "3"))

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
            if candidate.exists():
                return str(candidate)
            candidate.mkdir(parents=True, exist_ok=True)
            return str(candidate)
        except OSError as exc:
            fallback = Path(fallback_dir).expanduser()
            fallback.mkdir(parents=True, exist_ok=True)
            logger.warning(
                f"目录不可写，回退到本地目录: {candidate} -> {fallback} ({exc})"
            )
            return str(fallback)

    def load_runtime_settings(self) -> None:
        """从 JSON 文件加载运行时设置（启动时调用）"""
        if not RUNTIME_SETTINGS_FILE.exists():
            return
        try:
            with open(RUNTIME_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, value in data.items():
                if hasattr(self, key):
                    try:
                        setattr(self, key, value)
                    except (TypeError, ValueError):
                        pass
            logger.debug(f"已从 {RUNTIME_SETTINGS_FILE} 加载运行时设置")
        except Exception as e:
            logger.warning(f"加载运行时设置失败: {e}")

    def save_runtime_settings(self, settings_dict: dict) -> None:
        """保存运行时设置到 JSON 文件"""
        try:
            existing = {}
            if RUNTIME_SETTINGS_FILE.exists():
                with open(RUNTIME_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            existing.update(settings_dict)
            with open(RUNTIME_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            logger.debug(f"运行时设置已保存到 {RUNTIME_SETTINGS_FILE}")
        except Exception as e:
            logger.error(f"保存运行时设置失败: {e}")
            raise

    def update_runtime_settings(self, settings_dict: dict) -> None:
        """更新运行时设置（内存 + 持久化）"""
        for key, value in settings_dict.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save_runtime_settings(settings_dict)


# ==================== 模型注册表 ====================


class ModelRegistry:
    """模型注册表 - 从数据库加载模型配置，支持配置回退"""

    _instance: Optional["ModelRegistry"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._models: dict[str, dict] = {}
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._models.clear()
        try:
            from kb_core.database import init_model_db, init_vendor_db

            vendor_db = init_vendor_db()
            if not vendor_db.get_all(active_only=False):
                self._seed_default_vendors(vendor_db)

            model_db = init_model_db()
            rows = model_db.get_all(active_only=False)
            if rows:
                for row in rows:
                    self._models[row["id"]] = row
                logger.debug(f"从数据库加载了 {len(self._models)} 个模型")
                if "siliconflow/bge-m3" not in self._models:
                    self._models["siliconflow/bge-m3"] = {
                        "id": "siliconflow/bge-m3",
                        "vendor_id": "siliconflow",
                        "name": "bge-m3",
                        "type": "embedding",
                        "is_active": True,
                        "is_default": False,
                        "config": {},
                    }
            else:
                logger.debug("数据库为空，使用配置默认值并填充模型")
                self._load_defaults_from_config()
                self._seed_default_models(model_db)
        except Exception as e:
            logger.warning(f"模型数据库加载失败，使用配置默认值: {e}")
            self._load_defaults_from_config()
        self._loaded = True

    def _seed_default_models(self, model_db) -> None:
        """将默认 embedding 模型填充到数据库"""
        for model in self._models.values():
            if model["type"] == "embedding":
                model_db.upsert(**model)
        logger.debug(
            f"已填充 {len([m for m in self._models.values() if m['type'] == 'embedding'])} 个 embedding 模型"
        )

    def _seed_default_vendors(self, vendor_db):
        """填充默认供应商（仅 SiliconFlow，Ollama 需通过 CLI/API 管理）"""
        settings = get_settings()

        # SiliconFlow 是必须的（用于 reranker 和 fallback embedding）
        vendor_db.upsert(
            vendor_id="siliconflow",
            name="SiliconFlow",
            api_base=settings.siliconflow_base_url,
            api_key=settings.siliconflow_api_key,
        )

        logger.debug("已填充默认供应商: [siliconflow]")
        logger.debug(
            "注意: Ollama 供应商需通过 CLI 'vendor add' 或 API POST /vendors 添加"
        )

    def _load_defaults_from_config(self):
        """从配置加载默认模型（支持多端点 embedding）"""
        settings = get_settings()
        defaults = [
            {
                "id": f"siliconflow/{settings.siliconflow_model.split('/')[-1]}",
                "vendor_id": "siliconflow",
                "name": settings.siliconflow_model.split("/")[-1],
                "type": "llm",
                "is_active": True,
                "is_default": settings.llm_mode == "siliconflow",
                "config": {},
            },
            {
                "id": f"ollama/{settings.ollama_llm_model}",
                "vendor_id": "ollama",
                "name": settings.ollama_llm_model,
                "type": "llm",
                "is_active": True,
                "is_default": settings.llm_mode == "ollama",
                "config": {},
            },
            {
                "id": f"siliconflow/{settings.rerank_model.split('/')[-1]}",
                "vendor_id": "siliconflow",
                "name": settings.rerank_model.split("/")[-1],
                "type": "reranker",
                "is_active": True,
                "is_default": True,
                "config": {},
            },
        ]

        # Ollama embedding 模型：为每个端点创建独立记录
        embed_model_name = settings.ollama_embed_model
        vendor_ids = []
        if settings.ollama_local_url:
            vendor_ids.append("ollama")
        if (
            settings.ollama_remote_url
            and settings.ollama_remote_url != settings.ollama_local_url
        ):
            vendor_ids.append("ollama_home")
        if not vendor_ids:
            vendor_ids = ["ollama"]

        for i, vendor_id in enumerate(vendor_ids):
            model_id = f"{vendor_id}/{embed_model_name}"
            defaults.append(
                {
                    "id": model_id,
                    "vendor_id": vendor_id,
                    "name": embed_model_name,
                    "type": "embedding",
                    "is_active": True,
                    "is_default": i == 0,
                    "config": {},
                }
            )

        # SiliconFlow embedding 模型
        defaults.append(
            {
                "id": "siliconflow/bge-m3",
                "vendor_id": "siliconflow",
                "name": "bge-m3",
                "type": "embedding",
                "is_active": True,
                "is_default": False,
                "config": {},
            }
        )

        for model in defaults:
            self._models[model["id"]] = model

    def get_model(self, model_id: str) -> Optional[dict]:
        self._ensure_loaded()
        return self._models.get(model_id)

    def get_by_type(self, type: str) -> list[dict]:
        self._ensure_loaded()
        return [
            m
            for m in self._models.values()
            if m["type"] == type and m.get("is_active", True)
        ]

    def get_default(self, type: str) -> Optional[dict]:
        self._ensure_loaded()
        for m in self._models.values():
            if m.get("is_default") and m["type"] == type and m.get("is_active", True):
                return m
        for m in self._models.values():
            if m["type"] == type and m.get("is_active", True):
                return m
        return None

    def list_models(self, type: Optional[str] = None) -> list[dict]:
        self._ensure_loaded()
        if type:
            return self.get_by_type(type)
        return list(self._models.values())

    def reload(self):
        self._loaded = False
        self._ensure_loaded()


def get_model_registry() -> ModelRegistry:
    return ModelRegistry()


# 全局配置实例（延迟加载）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    获取全局配置实例（单例模式）
    首次调用时加载 .env 和运行时设置

    Returns:
        Settings: 配置实例
    """
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.load_runtime_settings()
    return _settings
