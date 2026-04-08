"""
Reranker 模块

提供两种重排序策略：

策略1（默认，推荐）：SiliconFlow 云端 Reranker
  - 调用 SiliconFlow 的 /v1/rerank 接口（OpenAI 兼容格式）
  - 模型：Pro/BAAI/bge-reranker-v2-m3
  - 准确性高，区分度好

策略2（离线备选）：基于 Embedding 相似度的 Reranker
  - 使用本地 bge-m3 embedding 模型
  - 不需要网络，但准确性低于 cross-encoder
"""

import json
import math
from typing import List

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle, MetadataMode
from pydantic import ConfigDict, Field


def _remove_surrogates(text: str) -> str:
    """Remove lone surrogate characters that cannot be encoded as UTF-8.

    Surrogates (U+D800-U+DFFF) are only valid in UTF-16, not UTF-8.
    When text contains unpaired surrogates, Python's JSON encoder fails
    with 'surrogates not allowed' error.
    """
    return "".join(c for c in text if not (0xD800 <= ord(c) <= 0xDFFF))


def _sanitize_for_json(text: str) -> str:
    """Sanitize text for JSON encoding by removing invalid surrogates."""
    return _remove_surrogates(text)


def _record_reranker_call(
    model_id: str,
    token_count: int,
    error: bool = False,
):
    """记录 Reranker 调用统计"""
    try:
        from llamaindex_study.callbacks import record_model_call

        record_model_call(
            vendor_id="siliconflow",
            model_type="reranker",
            model_id=model_id,
            prompt_tokens=token_count,
            completion_tokens=0,
            error=error,
        )
    except Exception:
        pass


def _record_embedding_call(
    vendor_id: str,
    model_id: str,
    token_count: int,
    error: bool = False,
):
    """记录 Embedding 调用统计"""
    try:
        from llamaindex_study.callbacks import record_model_call

        record_model_call(
            vendor_id=vendor_id,
            model_type="embedding",
            model_id=model_id,
            prompt_tokens=token_count,
            completion_tokens=0,
            error=error,
        )
    except Exception:
        pass


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _format_node_with_metadata(node: NodeWithScore) -> str:
    """将节点及其关键元数据格式化为 reranker 可理解的文本"""
    metadata = node.metadata or {}

    parts = []

    if file_name := metadata.get("file_name"):
        parts.append(f"[文档: {file_name}]")

    if page_label := metadata.get("page_label"):
        parts.append(f"[页码: {page_label}]")

    if source := metadata.get("source"):
        parts.append(f"[来源: {source}]")

    if categories := metadata.get("categories"):
        if isinstance(categories, list):
            parts.append(f"[分类: {' | '.join(categories)}]")

    text = node.get_content(metadata_mode=MetadataMode.NONE)
    if parts:
        return " ".join(parts) + f"\n{text}"
    return text


def get_default_reranker_from_registry() -> tuple[str, str, str]:
    """Get default reranker model name, API key, and base URL from the model registry.

    Returns:
        (model_name, api_key, base_url)
    """
    from kb.database import init_vendor_db
    from llamaindex_study.config import get_model_registry

    registry = get_model_registry()
    model = registry.get_default("reranker")
    if not model:
        raise RuntimeError(
            "No default reranker model found in registry. "
            "Please add a reranker model via CLI or API."
        )

    vendor_db = init_vendor_db()
    vendor_info = vendor_db.get(model["vendor_id"])
    if not vendor_info:
        raise RuntimeError(f"Vendor '{model['vendor_id']}' not found in database.")

    api_key = vendor_info.get("api_key", "")
    base_url = vendor_info.get("api_base", "https://api.siliconflow.cn/v1")

    return model["name"], api_key, base_url


class SiliconFlowReranker(BaseNodePostprocessor):
    """
    SiliconFlow 云端 Reranker（默认推荐）

    调用 SiliconFlow 的 /v1/rerank 接口，
    使用 BAAI/bge-reranker-v2-m3 对检索结果进行精确重排序。
    """

    model_config = ConfigDict(extra="allow")

    api_key: str = Field(description="SiliconFlow API Key")
    model: str = Field(default="Pro/BAAI/bge-reranker-v2-m3")
    base_url: str = Field(default="https://api.siliconflow.cn/v1")
    top_n: int = Field(default=5)

    def _postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: QueryBundle,
    ) -> List[NodeWithScore]:
        if not nodes:
            return nodes

        query = _sanitize_for_json(query_bundle.query_str)
        documents = [
            _sanitize_for_json(_format_node_with_metadata(node)) for node in nodes
        ]

        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(self.top_n, len(documents)),
        }

        print(f"   🔄 SiliconFlow Reranker: 正在对 {len(nodes)} 个结果进行重排序...")
        import httpx

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/rerank",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
                response.raise_for_status()
                result = response.json()
                api_results = result["results"]
                _record_reranker_call(self.model, sum(len(d) for d in documents), False)
        except Exception as e:
            _record_reranker_call(self.model, 0, True)
            raise

        # 建立 index → score 映射并更新节点
        index_to_score = {
            item["index"]: item["relevance_score"] for item in api_results
        }
        for node in nodes:
            node.score = index_to_score.get(nodes.index(node), 0.0)

        # 按新分数降序排列
        nodes.sort(key=lambda n: n.score or 0.0, reverse=True)
        print(f"   ✅ Reranker 完成: Top-{min(self.top_n, len(nodes))} 结果")
        return nodes[: self.top_n]

    # 独立调用接口（不依赖 LlamaIndex 的 NodeWithScore）
    def rerank(self, query: str, documents: List[str]) -> List[tuple]:
        """对文档列表进行重排序，返回 (文档, 分数) 列表"""
        query = _sanitize_for_json(query)
        documents = [_sanitize_for_json(d) for d in documents]
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }
        import httpx

        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/rerank",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                )
                response.raise_for_status()
                result = response.json()
                _record_reranker_call(self.model, sum(len(d) for d in documents), False)
                return [
                    (documents[item["index"]], item["relevance_score"])
                    for item in result["results"]
                ]
        except Exception as e:
            _record_reranker_call(self.model, 0, True)
            raise


class EmbeddingSimilarityReranker(BaseNodePostprocessor):
    """
    基于 Embedding 相似度的轻量 Reranker（离线备选）

    使用本地 bge-m3 embedding 模型计算 query 和文档的向量相似度，
    作为 rerank 分数对检索结果重新排序。
    """

    model_config = ConfigDict(extra="allow")

    embed_model: str = Field(default="bge-m3")
    base_url: str = Field(default="http://localhost:11434")
    top_n: int = Field(default=5)

    def _get_embedding(self, text: str) -> List[float]:
        """调用 Ollama 获取文本的 embedding 向量"""
        import httpx

        text = _sanitize_for_json(text[:2048])
        payload = {"model": self.embed_model, "prompt": text}
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{self.base_url}/api/embeddings",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                result = response.json()
                token_count = len(text[:2048]) // 4
                _record_embedding_call("ollama", self.embed_model, token_count, False)
                return result["embedding"]
        except Exception as e:
            _record_embedding_call("ollama", self.embed_model, 0, True)
            raise

    def _postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: QueryBundle,
    ) -> List[NodeWithScore]:
        if not nodes:
            return nodes

        print(f"   🔄 Embedding Reranker: 计算 {len(nodes)} 个文档的相似度...")
        query = query_bundle.query_str
        documents = [_format_node_with_metadata(node) for node in nodes]

        query_emb = self._get_embedding(query)
        doc_embs = [self._get_embedding(doc) for doc in documents]
        scores = [cosine_similarity(query_emb, emb) for emb in doc_embs]

        for node, score in zip(nodes, scores):
            node.score = score

        nodes.sort(key=lambda n: n.score or 0.0, reverse=True)
        print(f"   ✅ Reranker 完成: Top-{self.top_n} 结果")
        return nodes[: self.top_n]
