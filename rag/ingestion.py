"""
Ingestion Pipeline Module

Provides a unified document processing pipeline using LlamaIndex's
IngestionPipeline with TransformComponent architecture.

Key features:
- Declarative transformation chain (NodeParser + ReferenceDetector + TextCleaner)
- IngestionCache for incremental document processing
- Backward compatible with existing get_node_parser() / build_index() flow
- Pluggable metadata extractors

Usage:
    from rag.ingestion import create_ingestion_pipeline

    pipeline = create_ingestion_pipeline(kb_id="my_kb", strategy="hierarchical", ...)
    nodes = pipeline.run(documents=docs)
    # Then embed and store via existing OllamaEmbedder flow
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, List, Optional, Sequence

from llama_index.core.ingestion import IngestionPipeline, IngestionCache
from llama_index.core.node_parser import NodeParser
from llama_index.core.schema import Document as LlamaDocument, BaseNode

from rag.config import get_settings
from rag.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Inline Text Cleaner - light normalization without external dependencies
# ---------------------------------------------------------------------------

class TextCleanerTransform(NodeParser):
    """Lightweight text normalizer as a NodeParser-compatible transform.

    Strips excessive whitespace, removes zero-width characters, and
    normalizes Unicode punctuation. Does NOT change semantic content.
    """

    def _parse_nodes(
        self,
        nodes: list[BaseNode],
        **kwargs: Any,
    ) -> list[BaseNode]:
        import unicodedata

        for node in nodes:
            text = node.get_content()
            if not text:
                continue
            # Normalize Unicode (NFKC for full-width to half-width etc.)
            text = unicodedata.normalize("NFKC", text)
            # Remove zero-width characters
            text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
            text = text.replace("\ufeff", "")
            # Collapse 3+ consecutive blank lines
            import re

            text = re.sub(r"\n{3,}", "\n\n", text)
            # Strip leading/trailing whitespace per line
            lines = [line.strip() for line in text.split("\n")]
            text = "\n".join(lines)
            # Set cleaned content
            node.set_content(text)
        return nodes


class ContextEnricherTransform(NodeParser):
    """Prepend metadata context to node text for context-aware embedding.

    Transforms a node like:
        "细胞壁由纤维素构成"
    into:
        "[文档: botany.pdf | 分类: 植物学, 细胞]\\n细胞壁由纤维素构成"

    The enriched text is embedded, so the vector captures both content
    AND provenance. Original text is saved in ``_original_text`` metadata
    for recovery. No LLM calls — uses only existing metadata fields.
    """

    def __init__(self, *, prefix_template: str | None = None):
        super().__init__()
        self._prefix_template = prefix_template or "[{fields}]"

    def _build_context(self, metadata: dict) -> str:
        parts: list[str] = []
        if file_name := metadata.get("file_name"):
            parts.append(f"文档: {file_name}")
        if source := metadata.get("source"):
            parts.append(f"来源: {source}")
        if page_label := metadata.get("page_label"):
            parts.append(f"页码: {page_label}")
        if categories := metadata.get("categories"):
            if isinstance(categories, list):
                parts.append(f"分类: {', '.join(categories)}")
            else:
                parts.append(f"分类: {categories}")
        if not parts:
            return ""
        return self._prefix_template.format(fields=" | ".join(parts))

    def _parse_nodes(
        self,
        nodes: list[BaseNode],
        **kwargs: Any,
    ) -> list[BaseNode]:
        for node in nodes:
            text = node.get_content()
            if not text:
                continue
            metadata = node.metadata or {}
            prefix = self._build_context(metadata)
            if prefix:
                if "_original_text" not in metadata:
                    metadata["_original_text"] = text
                node.metadata = metadata
                node.set_content(f"{prefix}\n{text}")
        return nodes


# ---------------------------------------------------------------------------
# Reference Detector as TransformComponent
# ---------------------------------------------------------------------------

class ReferenceDetectorTransform(NodeParser):
    """Apply reference/bibliography detection to nodes during ingestion.

    Reads global reference_strategy from Settings and applies the
    corresponding flag/skip/none strategy to node metadata.
    """

    def __init__(
        self,
        strategy: Optional[str] = None,
    ):
        super().__init__()
        self._strategy = strategy

    def _parse_nodes(
        self,
        nodes: list[BaseNode],
        **kwargs: Any,
    ) -> list[BaseNode]:
        from kb_processing.reference_detector import apply_reference_strategy

        strategy: str | None = self._strategy
        return apply_reference_strategy(nodes, strategy=strategy)


# ---------------------------------------------------------------------------
# IngestionPipeline Factory
# ---------------------------------------------------------------------------

def _get_cache_dir(kb_id: str) -> Path:
    """Get the IngestionCache directory for a knowledge base."""
    settings = get_settings()
    base = Path(settings.llamaindex_storage_base)
    cache_dir = base / kb_id / "_ingestion_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _compute_doc_hash(document: LlamaDocument) -> str:
    """Compute a stable hash for a document to use as cache key."""
    content = document.get_content()
    metadata_str = str(sorted(document.metadata.items())) if document.metadata else ""
    combined = f"{content}|{metadata_str}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:24]


def create_ingestion_pipeline(
    kb_id: str,
    node_parser: NodeParser,
    *,
    enable_cache: bool = True,
    enable_text_cleaner: bool = True,
    enable_reference_detection: bool = True,
    enable_context_enrichment: bool = False,
    reference_strategy: Optional[str] = None,
    extra_transformations: Optional[List[Any]] = None,
) -> IngestionPipeline:
    """Create a configured IngestionPipeline for document processing.

    The pipeline handles node parsing, reference detection, and text
    cleaning. Embedding is intentionally kept OUTSIDE the pipeline to
    preserve OllamaEmbedder's retry/circuit-breaker infrastructure.

    Args:
        kb_id: Knowledge base identifier (used for cache isolation).
        node_parser: The primary node parser (HierarchicalNodeParser,
                     SemanticChunker, SentenceSplitter, etc.).
        enable_cache: Enable IngestionCache to skip re-parsing unchanged docs.
        enable_text_cleaner: Add TextCleanerTransform to normalize text.
        enable_reference_detection: Add ReferenceDetectorTransform.
        reference_strategy: Override global reference strategy ("flag"/"skip"/"none").
        extra_transformations: Additional TransformComponent instances injected
                               after node_parser and before the cleaners.

    Returns:
        Configured IngestionPipeline ready for ``pipeline.run(documents=...)``.
    """
    transformations: list[Any] = []

    # 1. Primary node parser (must come first: splits documents into nodes)
    transformations.append(node_parser)

    # 2. Extra transforms (e.g., MetadataExtractors — enrich metadata)
    if extra_transformations:
        transformations.extend(extra_transformations)

    # 3. Context enrichment (prepend metadata context before embedding)
    if enable_context_enrichment:
        transformations.append(ContextEnricherTransform())

    # 4. Reference detection (flag or skip bibliography chunks)
    if enable_reference_detection:
        transformations.append(
            ReferenceDetectorTransform(strategy=reference_strategy)
        )

    # 5. Text cleaner (normalize whitespace, Unicode, etc.)
    if enable_text_cleaner:
        transformations.append(TextCleanerTransform())

    # Ingestion cache (skip re-parsing unchanged documents)
    cache: Optional[IngestionCache] = None
    _cache_persist_path: Optional[str] = None
    if enable_cache:
        try:
            from llama_index.storage.kvstore.simple_kvstore import SimpleKVStore

            cache_dir = _get_cache_dir(kb_id)
            kvstore_path = cache_dir / "doc_cache.json"
            kvstore = SimpleKVStore()
            if kvstore_path.exists():
                try:
                    kvstore = SimpleKVStore.from_persist_path(str(kvstore_path))
                    logger.debug(f"Loaded ingestion cache: {kvstore_path}")
                except Exception as e:
                    logger.warning(f"Failed to load ingestion cache, starting fresh: {e}")
            cache = IngestionCache(
                cache=kvstore,
                collection=f"kb_{kb_id}",
            )
            _cache_persist_path = str(kvstore_path)
        except ImportError:
            logger.warning("SimpleKVStore unavailable, disabling ingestion cache")

    pipeline = IngestionPipeline(
        transformations=transformations,
        cache=cache,
    )

    pipeline._persist_path = _cache_persist_path  # type: ignore[attr-defined]

    return pipeline


def run_ingestion_pipeline(
    pipeline: IngestionPipeline,
    documents: List[LlamaDocument],
    *,
    show_progress: bool = True,
) -> list[BaseNode]:
    """Run the ingestion pipeline and persist cache if enabled.

    Args:
        pipeline: Configured IngestionPipeline from create_ingestion_pipeline().
        documents: List of LlamaIndex Documents to process.
        show_progress: Display a progress bar during processing.

    Returns:
        List of processed nodes (without embeddings - embed separately).
    """
    nodes = pipeline.run(documents=documents, show_progress=show_progress)

    persist_path = getattr(pipeline, "_persist_path", None)
    if persist_path and pipeline.cache:
        try:
            pipeline.cache.cache.persist(persist_path)
            logger.debug(f"Persisted ingestion cache: {persist_path}")
        except Exception as e:
            logger.warning(f"Failed to persist ingestion cache: {e}")

    return nodes


# ---------------------------------------------------------------------------
# Convenience: bridge existing get_node_parser() with pipeline
# ---------------------------------------------------------------------------

def build_nodes_with_pipeline(
    kb_id: str,
    documents: list[LlamaDocument],
    embed_model: Optional[Any] = None,
    *,
    strategy: str = "hierarchical",
    chunk_size: int = 1024,
    chunk_overlap: int = 100,
    hierarchical_chunk_sizes: Optional[List[int]] = None,
    enable_cache: bool = True,
    enable_text_cleaner: bool = True,
    enable_reference_detection: bool = True,
    enable_context_enrichment: bool = False,
    reference_strategy: Optional[str] = None,
    extra_transformations: Optional[List[Any]] = None,
    show_progress: bool = True,
) -> List[BaseNode]:
    """End-to-end convenience: documents → pipeline → nodes.

    This is a drop-in replacement for the manual flow:

        node_parser = get_node_parser(strategy=...)
        nodes = node_parser.get_nodes_from_documents(documents)

    It adds reference detection, text cleaning, and ingestion cache
    on top without changing the calling code structure.

    Args:
        kb_id: Knowledge base identifier.
        documents: LlamaIndex Documents to process.
        embed_model: Embedding model (required for semantic strategy).
        strategy: Chunking strategy (hierarchical/semantic/sentence/markdown/page/window).
        chunk_size: Default chunk size in tokens.
        chunk_overlap: Overlap between chunks.
        hierarchical_chunk_sizes: List of chunk sizes for hierarchical strategy.
        enable_cache: Use IngestionCache.
        enable_text_cleaner: Apply TextCleanerTransform.
        enable_reference_detection: Apply ReferenceDetectorTransform.
        reference_strategy: Override global reference strategy.
        extra_transformations: Additional transforms to inject.
        show_progress: Show progress bar.

    Returns:
        List of processed nodes (without embeddings).
    """
    from kb_processing.document_processor import get_node_parser

    node_parser = get_node_parser(
        strategy=strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        hierarchical_chunk_sizes=hierarchical_chunk_sizes,
        embed_model=embed_model,
    )

    pipeline = create_ingestion_pipeline(
        kb_id=kb_id,
        node_parser=node_parser,
        enable_cache=enable_cache,
        enable_text_cleaner=enable_text_cleaner,
        enable_reference_detection=enable_reference_detection,
        enable_context_enrichment=enable_context_enrichment,
        reference_strategy=reference_strategy,
        extra_transformations=extra_transformations,
    )

    return run_ingestion_pipeline(pipeline, documents, show_progress=show_progress)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "TextCleanerTransform",
    "ReferenceDetectorTransform",
    "create_ingestion_pipeline",
    "run_ingestion_pipeline",
    "build_nodes_with_pipeline",
]
