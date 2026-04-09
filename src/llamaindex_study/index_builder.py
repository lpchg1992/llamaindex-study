from pathlib import Path
from typing import List, Optional, Union

from llama_index.core.schema import Document as LlamaDocument

Index = any


def _configure_embed_model() -> None:
    from llama_index.core import Settings as LlamaSettings
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llamaindex_study.embedding_service import get_default_embedding_from_registry

    model_name, base_url = get_default_embedding_from_registry()

    LlamaSettings.embed_model = OllamaEmbedding(
        model_name=model_name,
        base_url=base_url,
    )


class IndexBuilder:
    def __init__(self, persist_dir: Optional[Union[str, Path]] = None):
        self.persist_dir = Path(persist_dir) if persist_dir else None

    def build_from_documents(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
    ) -> Index:
        from llama_index.core import VectorStoreIndex

        _configure_embed_model()

        index = VectorStoreIndex.from_documents(
            documents,
            show_progress=show_progress,
        )

        return index
