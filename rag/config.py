"""
配置管理模块

负责从 .env 文件加载配置，提供统一的配置访问接口。
仅保留与模型无关的全局设置（重试机制、功能开关、存储路径等）。
模型配置（供应商、API密钥、模型名称等）全部从数据库获取。

模型配置请通过 CLI 管理:
    uv run llamaindex-study vendor add --help
    uv run llamaindex-study model add --help
"""

import json
import os
from pathlib import Path
from typing import ClassVar, List, Optional

from dotenv import load_dotenv

from rag.logger import get_logger

logger = get_logger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_SETTINGS_FILE = PROJECT_ROOT / ".runtime_settings.json"


class Settings:
    """
    应用程序配置类

    提供类型安全的配置访问接口，自动从环境变量加载配置。
    注意：模型相关配置（供应商、API密钥、模型名称）全部从数据库获取，
    此处仅保留与模型无关的全局设置。
    """

    _DEFAULT_PERSIST_DIR: ClassVar[str] = str(PROJECT_ROOT / ".llamaindex" / "storage")
    _DEFAULT_ZOTERO_PERSIST_DIR: ClassVar[str] = str(
        PROJECT_ROOT / ".llamaindex" / "storage" / "zotero"
    )
    _DEFAULT_DATA_DIR: ClassVar[str] = str(Path.home() / ".llamaindex")
    _DEFAULT_TOP_K: ClassVar[int] = 5
    _DEFAULT_USE_RERANKER: ClassVar[bool] = False
    _DEFAULT_VECTOR_STORE_TYPE: ClassVar[str] = "lancedb"
    _DEFAULT_VECTOR_TABLE_NAME: ClassVar[str] = "llamaindex"
    _DEFAULT_QDRANT_URL: ClassVar[str] = "http://localhost:6333"

    def __init__(self) -> None:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        # ========== 重试机制 ==========
        self.max_retries: int = int(os.getenv("MAX_RETRIES", "5"))
        self.retry_delay: float = float(os.getenv("RETRY_DELAY", "2.0"))
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
        self.zotero_persist_dir: str = self._resolve_dir(
            os.getenv("ZOTERO_PERSIST_DIR", self._DEFAULT_ZOTERO_PERSIST_DIR),
            self._DEFAULT_ZOTERO_PERSIST_DIR,
        )
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
        self.use_reranker: bool = os.getenv("USE_RERANKER", "true").lower() == "true"

        # ========== 向量数据库配置 ==========
        self.vector_store_type: str = os.getenv(
            "VECTOR_STORE_TYPE", self._DEFAULT_VECTOR_STORE_TYPE
        )
        self.vector_db_uri: str = os.getenv("VECTOR_DB_URI", "")
        self.vector_table_name: str = os.getenv(
            "VECTOR_TABLE_NAME", self._DEFAULT_VECTOR_TABLE_NAME
        )
        self.qdrant_url: str = os.getenv("QDRANT_URL", self._DEFAULT_QDRANT_URL)
        self.qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")

        # ========== OCR 配置 ==========
        self.doc2x_api_key: Optional[str] = os.getenv("DOC2X_API_KEY")
        self.mineru_api_key: Optional[str] = os.getenv("MINERU_API_KEY")
        self.mineru_pipeline_id: Optional[str] = os.getenv("MINERU_PIPELINE_ID")

    def __repr__(self) -> str:
        return f"Settings(top_k={self.top_k})"

    def get_ollama_endpoints(self) -> list[tuple[str, str]]:
        """从数据库加载 Ollama 端点列表（不再从环境变量读取）"""
        from kb_core.database import init_vendor_db

        vendor_db = init_vendor_db()
        vendors = vendor_db.get_all(active_only=True)
        endpoints = []
        seen_urls = set()
        for v in vendors:
            vid = v.get("id", "")
            if vid.startswith("ollama"):
                base_url = v.get("api_base", "")
                if base_url and base_url not in seen_urls:
                    seen_urls.add(base_url)
                    endpoints.append((v.get("name", vid), base_url))
        return endpoints

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
    """模型注册表 - 从数据库加载模型配置"""

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
                self._seed_siliconflow_vendor(vendor_db)

            model_db = init_model_db()
            rows = model_db.get_all(active_only=False)
            if rows:
                for row in rows:
                    self._models[row["id"]] = row
                logger.debug(f"从数据库加载了 {len(self._models)} 个模型")
            else:
                logger.warning("模型数据库为空，请通过 CLI 添加模型: uv run llamaindex-study model add")
        except Exception as e:
            logger.error(f"模型数据库加载失败: {e}")
        self._loaded = True

    def _seed_siliconflow_vendor(self, vendor_db):
        """创建 SiliconFlow 供应商占位符（API密钥需通过 CLI 配置）"""
        vendor_db.upsert(
            vendor_id="siliconflow",
            name="SiliconFlow",
            api_base="https://api.siliconflow.cn/v1",
            api_key=None,
        )
        logger.info("已创建 SiliconFlow 供应商占位符，请通过 CLI 配置 API 密钥: uv run llamaindex-study vendor update siliconflow --api-key=YOUR_KEY")

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
