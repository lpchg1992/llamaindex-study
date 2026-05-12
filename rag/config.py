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
    _DEFAULT_API_PORT: ClassVar[int] = 37241
    _DEFAULT_PROGRESS_UPDATE_INTERVAL: ClassVar[int] = 10
    _DEFAULT_MAX_CONCURRENT_TASKS: ClassVar[int] = 10
    _DEFAULT_HEARTBEAT_INTERVAL: ClassVar[int] = 30
    _DEFAULT_STALE_TASK_TIMEOUT: ClassVar[int] = 300
    _DEFAULT_EMBED_CONCURRENT_POOL: ClassVar[int] = 16
    _DEFAULT_EMBED_ENDPOINT_MAX_CONCURRENT: ClassVar[int] = 8

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
        self.retrieval_oversampling_factor: int = int(
            os.getenv("RETRIEVAL_OVERSAMPLING_FACTOR", "5")
        )
        self.auto_merging_simple_ratio_thresh: float = float(
            os.getenv("AUTO_MERGING_SIMPLE_RATIO_THRESH", "0.5")
        )
        self.use_hybrid_search: bool = (
            os.getenv("USE_HYBRID_SEARCH", "false").lower() == "true"
        )
        self.hybrid_search_alpha: float = float(os.getenv("HYBRID_SEARCH_ALPHA", "0.5"))
        self.hybrid_search_mode: str = os.getenv("HYBRID_SEARCH_MODE", "relative_score")
        self.chunk_size: int = int(os.getenv("CHUNK_SIZE", "1024"))
        self.chunk_overlap: int = int(os.getenv("CHUNK_OVERLAP", "100"))
        self.embed_batch_size: int = int(os.getenv("EMBED_BATCH_SIZE", "32"))
        self.embed_concurrent_pool_size: int = int(
            os.getenv("EMBED_CONCURRENT_POOL_SIZE", "16")
        )
        self.embed_endpoint_max_concurrent: int = int(
            os.getenv("EMBED_ENDPOINT_MAX_CONCURRENT", "8")
        )
        self.embed_endpoint_concurrent_map: dict = self._parse_concurrent_map(
            os.getenv("EMBED_ENDPOINT_CONCURRENT_MAP", "")
        )

        # ========== 分块策略配置 ==========
        self.chunk_strategy: str = os.getenv("CHUNK_STRATEGY", "hierarchical")
        self.hierarchical_chunk_sizes: List[int] = [
            int(x)
            for x in os.getenv("HIERARCHICAL_CHUNK_SIZES", "1024,512,256").split(",")
        ]
        self.window_size: int = int(os.getenv("WINDOW_SIZE", "3"))
        self.use_ingestion_pipeline: bool = (
            os.getenv("USE_INGESTION_PIPELINE", "false").lower() == "true"
        )
        self.enable_context_enrichment: bool = (
            os.getenv("ENABLE_CONTEXT_ENRICHMENT", "false").lower() == "true"
        )

        # ========== 语义分块配置 ==========
        self.semantic_chunking_similarity_threshold: float = float(
            os.getenv("SEMANTIC_CHUNKING_SIMILARITY_THRESH", "0.5")
        )
        self.semantic_chunking_percentile_threshold: Optional[float] = None
        _percentile_env = os.getenv("SEMANTIC_CHUNKING_PERCENTILE_THRESH")
        if _percentile_env:
            self.semantic_chunking_percentile_threshold = float(
                _percentile_env
            )

        # ========== 参考文献检测配置 ==========
        self.reference_strong_ratio: float = float(
            os.getenv("REFERENCE_STRONG_RATIO", "0.5")
        )
        self.reference_moderate_ratio: float = float(
            os.getenv("REFERENCE_MODERATE_RATIO", "0.3")
        )
        self.reference_weak_ratio: float = float(
            os.getenv("REFERENCE_WEAK_RATIO", "0.4")
        )
        self.reference_moderate_min_matches: int = int(
            os.getenv("REFERENCE_MODERATE_MIN_MATCHES", "5")
        )
        self.reference_weak_min_matches: int = int(
            os.getenv("REFERENCE_WEAK_MIN_MATCHES", "3")
        )
        self.reference_weak_min_strong: int = int(
            os.getenv("REFERENCE_WEAK_MIN_STRONG", "2")
        )

        # ========== PDF 检测配置 ==========
        self.pdf_scan_threshold: float = float(
            os.getenv("PDF_SCAN_THRESHOLD", "10.0")
        )
        self.pdf_image_ratio_threshold: float = float(
            os.getenv("PDF_IMAGE_RATIO_THRESHOLD", "0.8")
        )

        # ========== Query Transform 配置 ==========
        self.use_hyde: bool = os.getenv("USE_HYDE", "false").lower() == "true"
        self.use_multi_query: bool = (
            os.getenv("USE_MULTI_QUERY", "false").lower() == "true"
        )
        self.num_multi_queries: int = int(os.getenv("MULTI_QUERY_NUM", "3"))
        self.multi_query_variant_score_threshold: float = float(
            os.getenv("MULTI_QUERY_VARIANT_SCORE_THRESHOLD", "0.5")
        )
        self.multi_query_original_weight: float = float(
            os.getenv("MULTI_QUERY_ORIGINAL_WEIGHT", "1.5")
        )

        # ========== Response Synthesizer 配置 ==========
        self.response_mode: str = os.getenv("RESPONSE_MODE", "compact")

        # ========== Reranker 配置 ==========
        self.use_reranker: bool = os.getenv("USE_RERANKER", "true").lower() == "true"

        # ========== Node Postprocessor 配置 ==========
        self.enable_similarity_filter: bool = (
            os.getenv("ENABLE_SIMILARITY_FILTER", "false").lower() == "true"
        )
        self.similarity_filter_cutoff: float = float(
            os.getenv("SIMILARITY_FILTER_CUTOFF", "0.3")
        )
        self.enable_long_context_reorder: bool = (
            os.getenv("ENABLE_LONG_CONTEXT_REORDER", "false").lower() == "true"
        )

        # ========== 参考文献过滤配置 ==========
        self.reference_strategy: str = os.getenv(
            "REFERENCE_STRATEGY", "flag"
        )  # "flag" | "skip" | "none"
        VALID_STRATEGIES = {"flag", "skip", "none"}
        if self.reference_strategy not in VALID_STRATEGIES:
            logger.warning(f"Invalid REFERENCE_STRATEGY='{self.reference_strategy}', defaulting to 'flag'")
            self.reference_strategy = "flag"

        # ========== 向量数据库配置 ==========
        self.vector_store_type: str = os.getenv(
            "VECTOR_STORE_TYPE", self._DEFAULT_VECTOR_STORE_TYPE
        )
        self.vector_table_name: str = os.getenv(
            "VECTOR_TABLE_NAME", self._DEFAULT_VECTOR_TABLE_NAME
        )

        # ========== OCR 配置 ==========
        self.doc2x_api_key: Optional[str] = os.getenv("DOC2X_API_KEY")
        self.mineru_api_key: Optional[str] = os.getenv("MINERU_API_KEY")
        self.mineru_pipeline_id: Optional[str] = os.getenv("MINERU_PIPELINE_ID")

        # ========== 存储路径配置 ==========
        self.obsidian_vault_root: str = self._resolve_dir(
            os.getenv("OBSIDIAN_VAULT_ROOT", str(Path.home() / "Documents" / "Obsidian Vault")),
            str(Path.home() / "Documents" / "Obsidian Vault"),
        )
        self.zotero_storage_dir: str = self._resolve_dir(
            os.getenv("ZOTERO_STORAGE_DIR", str(Path.home() / ".llamaindex" / "storage" / "zotero")),
            str(Path.home() / ".llamaindex" / "storage" / "zotero"),
        )

        # ========== 任务处理配置 ==========
        self.progress_update_interval: int = int(
            os.getenv("PROGRESS_UPDATE_INTERVAL", str(self._DEFAULT_PROGRESS_UPDATE_INTERVAL))
        )
        self.max_concurrent_tasks: int = int(
            os.getenv("MAX_CONCURRENT_TASKS", str(self._DEFAULT_MAX_CONCURRENT_TASKS))
        )
        self.heartbeat_interval: int = int(
            os.getenv("HEARTBEAT_INTERVAL", str(self._DEFAULT_HEARTBEAT_INTERVAL))
        )
        self.stale_task_timeout: int = int(
            os.getenv("STALE_TASK_TIMEOUT", str(self._DEFAULT_STALE_TASK_TIMEOUT))
        )

        # ========== API 服务配置 ==========
        self.api_port: int = int(os.getenv("API_PORT", str(self._DEFAULT_API_PORT)))
        self.cors_extra_origins: str = os.getenv("CORS_EXTRA_ORIGINS", "")

        # ========== 知识库存储根目录 ==========
        self.llamaindex_storage_base: str = self._resolve_dir(
            os.getenv("LLAMAINDEX_STORAGE_BASE", str(Path.home() / ".llamaindex" / "storage")),
            str(Path.home() / ".llamaindex" / "storage"),
        )

        self._defaults = self._snapshot_defaults()

    def _snapshot_defaults(self) -> dict:
        return {
            "embed_batch_size": self.embed_batch_size,
            "top_k": self.top_k,
            "use_semantic_chunking": self.use_semantic_chunking,
            "use_hybrid_search": self.use_hybrid_search,
            "use_auto_merging": self.use_auto_merging,
            "auto_merging_simple_ratio_thresh": self.auto_merging_simple_ratio_thresh,
            "retrieval_oversampling_factor": self.retrieval_oversampling_factor,
            "use_hyde": self.use_hyde,
            "use_multi_query": self.use_multi_query,
            "num_multi_queries": self.num_multi_queries,
            "multi_query_variant_score_threshold": self.multi_query_variant_score_threshold,
            "multi_query_original_weight": self.multi_query_original_weight,
            "hybrid_search_alpha": self.hybrid_search_alpha,
            "hybrid_search_mode": self.hybrid_search_mode,
            "chunk_strategy": self.chunk_strategy,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "hierarchical_chunk_sizes": self.hierarchical_chunk_sizes,
            "window_size": self.window_size,
            "use_ingestion_pipeline": self.use_ingestion_pipeline,
            "enable_context_enrichment": self.enable_context_enrichment,
            "use_reranker": self.use_reranker,
            "reference_strategy": self.reference_strategy,
            "semantic_chunking_similarity_threshold": self.semantic_chunking_similarity_threshold,
            "semantic_chunking_percentile_threshold": self.semantic_chunking_percentile_threshold,
            "reference_strong_ratio": self.reference_strong_ratio,
            "reference_moderate_ratio": self.reference_moderate_ratio,
            "reference_weak_ratio": self.reference_weak_ratio,
            "reference_moderate_min_matches": self.reference_moderate_min_matches,
            "reference_weak_min_matches": self.reference_weak_min_matches,
            "reference_weak_min_strong": self.reference_weak_min_strong,
            "pdf_scan_threshold": self.pdf_scan_threshold,
            "pdf_image_ratio_threshold": self.pdf_image_ratio_threshold,
            "response_mode": self.response_mode,
            "progress_update_interval": self.progress_update_interval,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "embed_concurrent_pool_size": self.embed_concurrent_pool_size,
            "embed_endpoint_max_concurrent": self.embed_endpoint_max_concurrent,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "ollama_short_text_threshold": self.ollama_short_text_threshold,
            "ollama_fanout_text_threshold": self.ollama_fanout_text_threshold,
            "heartbeat_interval": self.heartbeat_interval,
            "stale_task_timeout": self.stale_task_timeout,
            "mineru_pipeline_id": self.mineru_pipeline_id,
            "mineru_api_key": self.mineru_api_key or "",
            "doc2x_api_key": self.doc2x_api_key or "",
            "api_port": self.api_port,
            "cors_extra_origins": self.cors_extra_origins,
        }

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

    @staticmethod
    def _parse_concurrent_map(raw: str) -> dict:
        """Parse EMBED_ENDPOINT_CONCURRENT_MAP into {url_substring: concurrency}.

        Format: "substring1:concurrency1,substring2:concurrency2,..."
        Example: "192.168:12,localhost:6"
        """
        result = {}
        if not raw.strip():
            return result
        for pair in raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            parts = pair.rsplit(":", 1)
            if len(parts) == 2:
                try:
                    result[parts[0].strip()] = int(parts[1].strip())
                except ValueError:
                    continue
        return result

    def load_runtime_settings(self) -> None:
        """从 JSON 文件加载运行时设置 — 仅应用与当前默认值不同的缓存值"""
        if not RUNTIME_SETTINGS_FILE.exists():
            return
        try:
            with open(RUNTIME_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            applied = 0
            for key, value in data.items():
                if not hasattr(self, key):
                    continue
                default = self._defaults.get(key)
                if default is not None and isinstance(value, type(default)):
                    if isinstance(value, float):
                        if abs(value - default) < 1e-9:
                            continue
                    elif value == default:
                        continue
                try:
                    setattr(self, key, value)
                    applied += 1
                except (TypeError, ValueError):
                    pass
            logger.debug(
                f"已从 {RUNTIME_SETTINGS_FILE} 加载运行时设置 ({applied} 项覆盖, {len(data)} 项缓存)"
            )
        except Exception as e:
            logger.warning(f"加载运行时设置失败: {e}")

    def save_runtime_settings(self, settings_dict: dict) -> None:
        """保存运行时设置到 JSON 文件（仅保存与默认值不同的字段）"""
        try:
            existing = {}
            if RUNTIME_SETTINGS_FILE.exists():
                with open(RUNTIME_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            delta = {}
            for key, value in settings_dict.items():
                default = self._defaults.get(key)
                if default is None:
                    delta[key] = value
                elif isinstance(value, float) and isinstance(default, float):
                    if abs(value - default) > 1e-9:
                        delta[key] = value
                elif value != default:
                    delta[key] = value
            if delta:
                existing.update(delta)
                with open(RUNTIME_SETTINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2, ensure_ascii=False)
                logger.debug(f"运行时设置已保存 (delta): {list(delta.keys())}")
        except Exception as e:
            logger.error(f"保存运行时设置失败: {e}")
            raise

    def update_runtime_settings(self, settings_dict: dict) -> None:
        """更新运行时设置（内存 + 持久化）"""
        for key, value in settings_dict.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save_runtime_settings(settings_dict)


# ==============================================================================
# 模型注册表 (ModelRegistry)
# ==============================================================================
#
# 注意：此处的 "Registry" 是 RAG 模型配置注册表，与 kb_core/registry.py 中的
# "KnowledgeBaseRegistry"（知识库注册表）是完全不同的概念！
#
# 设计背景：
#   - Settings (.env) 负责 "静态配置"：重试次数、分块大小、开关等
#   - ModelRegistry (DB) 负责 "模型配置"：LLM/Embedding/Reranker 模型
#
# 为什么分开？
#   1. 模型配置需要运行时动态添加/切换（如通过 WebUI）
#   2. 模型配置包含敏感信息（API密钥）
#   3. 模型配置需要支持热更新（reload()），无需重启服务
#
# 存储位置：
#   - 模型元数据：kb_core/database.py 的 models 表
#   - 供应商配置：kb_core/database.py 的 vendors 表
#
# 使用方式：
#   from rag.config import get_model_registry
#   registry = get_model_registry()
#   registry.get_by_type("embedding")  # 获取所有 embedding 模型
#   registry.get_default("llm")       # 获取默认 LLM
#


class ModelRegistry:
    """
    模型配置注册表（与知识库注册表完全不同！）

    职责：管理 LLM、Embedding、Reranker 模型配置
    数据来源：kb_core/database.py 的 models 表 + vendors 表
    存储内容：模型 ID、供应商、API密钥、config(JSON) 等

    与 Settings 的区别：
      Settings = .env 静态配置（分块大小、开关等）
      ModelRegistry = 数据库模型配置（供应商、API密钥等）
    """

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
