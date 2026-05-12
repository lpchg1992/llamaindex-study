"""
Pluggable metadata extractors for node enrichment during ingestion.

Each extractor is LlamaIndex-native and runs as a TransformComponent,
injectable into the IngestionPipeline via ``extra_transformations``.

Available extractors:
- TitleExtractor: generates a descriptive title per chunk
- SummaryExtractor: generates a one-sentence summary per chunk
- QuestionsAnsweredExtractor: generates questions this chunk can answer
- KeywordExtractor: extracts key terms for improved recall

Extractors are opt-in and disabled by default (they consume LLM tokens).
"""

from __future__ import annotations

from typing import Any, List, Optional

from llama_index.core.extractors import (
    TitleExtractor,
    SummaryExtractor,
    QuestionsAnsweredExtractor,
    KeywordExtractor,
)

from rag.logger import get_logger

logger = get_logger(__name__)


def create_metadata_extractors(
    llm: Any,
    *,
    enable_title: bool = False,
    enable_summary: bool = False,
    enable_questions: bool = False,
    enable_keywords: bool = False,
    title_nodes: int = 5,
    summary_nodes: int = 5,
    questions: int = 3,
    keywords: int = 5,
) -> list[Any]:
    """Build a list of enabled metadata extractors.

    Each extractor makes LLM calls per-node, so they are disabled by
    default. Enable selectively based on use case:

    - ``enable_keywords=True``: lightest, useful for hybrid retrieval
    - ``enable_questions=True``: improves Q&A recall
    - ``enable_summary=True``: useful for search result previews
    - ``enable_title=True``: useful for navigation and clustering

    Args:
        llm: LLM instance used by extractors (must support .complete()).
        enable_title: Add TitleExtractor.
        enable_summary: Add SummaryExtractor.
        enable_questions: Add QuestionsAnsweredExtractor.
        enable_keywords: Add KeywordExtractor (lightest token cost).
        title_nodes: Number of neighbor nodes for title context.
        summary_nodes: Number of neighbor nodes for summary context.
        questions: Number of questions to generate per chunk.
        keywords: Number of keywords to extract per chunk.

    Returns:
        List of extractor instances ready for injection into IngestionPipeline.
    """
    extractors: list[Any] = []

    if enable_title:
        extractors.append(
            TitleExtractor(
                llm=llm,
                nodes=title_nodes,
            )
        )
        logger.info(f"TitleExtractor enabled (nodes={title_nodes})")

    if enable_summary:
        extractors.append(
            SummaryExtractor(
                llm=llm,
                summaries=["self"],
            )
        )
        logger.info("SummaryExtractor enabled")

    if enable_questions:
        extractors.append(
            QuestionsAnsweredExtractor(
                llm=llm,
                questions=questions,
            )
        )
        logger.info(f"QuestionsAnsweredExtractor enabled (questions={questions})")

    if enable_keywords:
        extractors.append(
            KeywordExtractor(
                llm=llm,
                keywords=keywords,
            )
        )
        logger.info(f"KeywordExtractor enabled (keywords={keywords})")

    if not extractors:
        logger.warning(
            "No metadata extractors enabled. Set enable_* flags to True "
            "to enrich nodes during ingestion."
        )

    return extractors


__all__ = [
    "TitleExtractor",
    "SummaryExtractor",
    "QuestionsAnsweredExtractor",
    "KeywordExtractor",
    "create_metadata_extractors",
]
