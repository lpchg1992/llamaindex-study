"""
配置管理模块

负责从 .env 文件加载配置，提供统一的配置访问接口。
支持：
  - LLM：硅基流动（SiliconFlow，OpenAI 兼容格式）
  - Embedding：本地 Ollama（nomic-embed-text）
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


class Settings:
    """应用程序配置类"""

    def __init__(self):
        """初始化配置，从环境变量加载所有配置项"""
        # 加载 .env 文件
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        # ========== LLM 配置（硅基流动）==========
        self.siliconflow_base_url: str = os.getenv(
            "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
        )
        self.siliconflow_api_key: Optional[str] = os.getenv("SILICONFLOW_API_KEY")
        self.siliconflow_model: str = os.getenv(
            "SILICONFLOW_MODEL", "Pro/deepseek-ai/DeepSeek-V3.2"
        )

        # ========== Embedding 配置（本地 Ollama）==========
        self.ollama_base_url: str = os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.ollama_embed_model: str = os.getenv(
            "OLLAMA_EMBED_MODEL", "nomic-embed-text"
        )

        # ========== 索引配置 ==========
        self.persist_dir: str = os.getenv("PERSIST_DIR", "/Volumes/online/llamaindex/obsidian")
        
        # Zotero 向量数据存储目录
        self.zotero_persist_dir: str = os.getenv("ZOTERO_PERSIST_DIR", "/Volumes/online/llamaindex/zotero")
        
        # 任务队列数据目录
        self.data_dir: str = os.getenv("DATA_DIR", "/Users/luopingcheng/.llamaindex")

        # ========== 检索配置 ==========
        self.top_k: int = int(os.getenv("TOP_K", "5"))

        # ========== Reranker 配置 ==========
        self.rerank_model: str = os.getenv(
            "RERANK_MODEL", "Pro/BAAI/bge-reranker-v2-m3"
        )
        self.use_reranker: bool = os.getenv("USE_RERANKER", "true").lower() == "true"

        # ========== 向量数据库配置 ==========
        self.vector_store_type: str = os.getenv("VECTOR_STORE_TYPE", "lancedb")
        self.vector_db_uri: str = os.getenv("VECTOR_DB_URI", "")
        self.vector_table_name: str = os.getenv("VECTOR_TABLE_NAME", "llamaindex")

        # Qdrant 专用配置
        self.qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")

    def __repr__(self) -> str:
        """返回配置的字符串表示"""
        return (
            f"Settings("
            f"llm=siliconflow:{self.siliconflow_model}, "
            f"embed=ollama:{self.ollama_embed_model}, "
            f"top_k={self.top_k})"
        )


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
