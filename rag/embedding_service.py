"""
Embedding 服务模块

提供：
- SiliconFlowEmbedding（SiliconFlow 云端 embedding）
- get_default_embedding_from_registry()
"""

from typing import List, Optional

from rag.config import get_model_registry
from rag.logger import get_logger

logger = get_logger(__name__)


def _remove_surrogates(text: str) -> str:
    """Remove lone surrogate characters that cannot be encoded as UTF-8."""
    return "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))


def get_default_embedding_from_registry() -> tuple[str, str]:
    """Get default embedding model name and URL from the model registry."""
    from kb_core.database import init_vendor_db

    registry = get_model_registry()
    model = registry.get_default("embedding")
    if not model:
        raise RuntimeError(
            "No default embedding model found in registry. "
            "Please add an embedding model via CLI: uv run llamaindex-study model add --help"
        )

    vendor_db = init_vendor_db()
    vendor_info = vendor_db.get(model["vendor_id"])
    if not vendor_info or not vendor_info.get("api_base"):
        raise RuntimeError(
            f"Vendor {model['vendor_id']} not configured. "
            f"Please add vendor via CLI: uv run llamaindex-study vendor add --help"
        )

    return model["name"], vendor_info["api_base"]


class SiliconFlowEmbedding:
    """SiliconFlow 云端 Embedding"""

    def __init__(
        self,
        model: str,
        dimensions: int = 1024,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        internal_model_id: Optional[str] = None,
    ):
        if not api_key or not base_url:
            from kb_core.database import init_vendor_db
            vendor_db = init_vendor_db()
            vendor = vendor_db.get("siliconflow")
            if vendor:
                api_key = api_key or vendor.get("api_key")
                base_url = base_url or vendor.get("api_base")

        if not api_key:
            raise ValueError("SiliconFlow API key not configured. Run: uv run llamaindex-study vendor update siliconflow --api-key=YOUR_KEY")
        if not base_url:
            raise ValueError("SiliconFlow base_url not configured.")

        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key
        self.base_url = base_url
        self._internal_model_id = internal_model_id or f"siliconflow/{model.split('/')[-1]}"
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=60.0)
        return self._client

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _record_embedding_call(self, token_count: int, error: bool):
        try:
            from rag.callbacks import record_model_call
            record_model_call(
                vendor_id="siliconflow",
                model_type="embedding",
                model_id=self._internal_model_id,
                prompt_tokens=token_count,
                completion_tokens=0,
                error=error,
            )
        except Exception as e:
            logger.warning(f"Failed to record embedding call for {self._internal_model_id}: {e}")

    def get_text_embedding(self, text: str) -> List[float]:
        results = self.get_text_embeddings([text])
        return results[0]

    def get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        texts = [_remove_surrogates(t) for t in texts]
        payload = {"model": self.model, "input": texts}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            client = self._get_client()
            response = client.post(
                f"{self.base_url}/embeddings", json=payload, headers=headers
            )
            if response.status_code != 200:
                logger.error(
                    f"SiliconFlow embedding 失败: {response.status_code} {response.text}"
                )
                total_tokens = sum(self._estimate_tokens(t) for t in texts)
                self._record_embedding_call(total_tokens, True)
                return [[0.0] * self.dimensions for _ in texts]

            data = response.json()
            embeddings = data.get("data", [])
            total_tokens = sum(self._estimate_tokens(t) for t in texts)
            self._record_embedding_call(total_tokens, False)
            embedding_map = {item["index"]: item["embedding"] for item in embeddings}
            return [
                embedding_map.get(i, [0.0] * self.dimensions) for i in range(len(texts))
            ]
        except Exception as e:
            logger.error(f"SiliconFlow embedding 请求异常: {e}")
            total_tokens = sum(self._estimate_tokens(t) for t in texts)
            self._record_embedding_call(total_tokens, True)
            return [[0.0] * self.dimensions for _ in texts]

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
