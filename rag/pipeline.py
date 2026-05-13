"""
声明式 QueryPipeline 模块

将检索流程从命令式代码转换为声明式 DAG 配置，
支持可视化、序列化、模块复用。

Usage:
    from rag.pipeline import create_qa_pipeline

    pipeline = create_qa_pipeline(kb_id="my_kb", top_k=5, use_reranker=True)
    response = pipeline.run(query="What is RAG?")
"""

from typing import Any, Dict, List, Optional

from rag.config import get_settings
from rag.logger import get_logger

logger = get_logger(__name__)


def _build_retriever_module(
    kb_id: str,
    mode: str = "vector",
    top_k: int = 5,
    use_auto_merging: bool = False,
):
    from kb_core.services import VectorStoreService
    from llama_index.core.query_pipeline import (
        CustomQueryComponent, InputKeys, OutputKeys
    )

    vector_store = VectorStoreService.get_vector_store(kb_id)
    index = vector_store.load_index()
    if index is None:
        raise ValueError(f"Knowledge base {kb_id} not found")

    class RetrieverComponent(CustomQueryComponent):
        def _validate_component_inputs(self, input: Dict[str, Any]) -> Dict[str, Any]:
            return input

        @property
        def _input_keys(self) -> InputKeys:
            return InputKeys.from_keys({"query_str"})

        @property
        def _output_keys(self) -> OutputKeys:
            return OutputKeys.from_keys({"nodes"})

        def _run_component(self, **kwargs) -> Dict:
            query_str = kwargs["query_str"]
            retriever = index.as_retriever(similarity_top_k=top_k)
            nodes = retriever.retrieve(query_str)
            return {"nodes": nodes}

    return RetrieverComponent()


def _build_reranker_module():
    from llama_index.core.query_pipeline import (
        CustomQueryComponent, InputKeys, OutputKeys
    )

    class RerankerComponent(CustomQueryComponent):
        def _validate_component_inputs(self, input: Dict[str, Any]) -> Dict[str, Any]:
            return input

        @property
        def _input_keys(self) -> InputKeys:
            return InputKeys.from_keys({"nodes", "query_str"})

        @property
        def _output_keys(self) -> OutputKeys:
            return OutputKeys.from_keys({"nodes"})

        def _run_component(self, **kwargs) -> Dict:
            nodes = kwargs["nodes"]
            query_str = kwargs["query_str"]
            from rag.query_engine import apply_reranker
            reranked = apply_reranker(nodes, query_str)
            return {"nodes": reranked}

    return RerankerComponent()


def _build_synthesizer_module(
    response_mode: str = "compact",
    model_id: Optional[str] = None,
):
    from llama_index.core.query_pipeline import (
        CustomQueryComponent, InputKeys, OutputKeys
    )

    class SynthesizerComponent(CustomQueryComponent):
        def _validate_component_inputs(self, input: Dict[str, Any]) -> Dict[str, Any]:
            return input

        @property
        def _input_keys(self) -> InputKeys:
            return InputKeys.from_keys({"nodes", "query_str"})

        @property
        def _output_keys(self) -> OutputKeys:
            return OutputKeys.from_keys({"response"})

        def _run_component(self, **kwargs) -> Dict:
            nodes = kwargs["nodes"]
            query_str = kwargs["query_str"]
            from llama_index.core.query_engine import RetrieverQueryEngine
            from llama_index.core import Settings
            from rag.ollama_utils import create_llm
            llm = create_llm(model_id=model_id)
            engine = RetrieverQueryEngine.from_args(
                retriever=_FakeRetriever(nodes),
                llm=llm,
                response_mode=response_mode,
            )
            response = engine.query(query_str)
            return {"response": response}

    return SynthesizerComponent()


class _FakeRetriever:
    def __init__(self, nodes: list):
        self._nodes = nodes

    def retrieve(self, query_str: str) -> list:
        return self._nodes


def create_search_pipeline(
    kb_id: str,
    *,
    mode: str = "vector",
    top_k: int = 5,
    use_reranker: Optional[bool] = None,
) -> Any:
    settings = get_settings()
    if use_reranker is None:
        use_reranker = settings.use_reranker

    from llama_index.core.query_pipeline import QueryPipeline, Link

    pipeline = QueryPipeline()

    retriever = _build_retriever_module(
        kb_id=kb_id, mode=mode, top_k=top_k
    )
    pipeline.add_module("input", retriever)

    if use_reranker:
        reranker = _build_reranker_module()
        pipeline.add_module("reranker", reranker)
        pipeline.add_link("input", "reranker", src_key="nodes", dest_key="nodes")
        pipeline.add_link("input", "reranker", src_key="query_str", dest_key="query_str")

    return pipeline


def create_qa_pipeline(
    kb_id: str,
    *,
    mode: str = "vector",
    top_k: int = 5,
    use_reranker: Optional[bool] = None,
    use_hyde: bool = False,
    use_multi_query: bool = False,
    response_mode: str = "compact",
    model_id: Optional[str] = None,
) -> Any:
    settings = get_settings()
    if use_reranker is None:
        use_reranker = settings.use_reranker

    from llama_index.core.query_pipeline import QueryPipeline, Link, InputComponent

    pipeline = QueryPipeline()

    retriever = _build_retriever_module(
        kb_id=kb_id, mode=mode, top_k=top_k
    )
    input_component = InputComponent()
    pipeline.add_module("input", input_component)

    if use_multi_query:
        pipeline.add_module("retriever", retriever)
        pipeline.add_link("input", "retriever", src_key="query_str", dest_key="query_str")
    else:
        pipeline.add_module("retriever", retriever)
        pipeline.add_link("input", "retriever", src_key="query_str", dest_key="query_str")

    if use_reranker:
        reranker = _build_reranker_module()
        pipeline.add_module("reranker", reranker)
        pipeline.add_link(
            "retriever", "reranker", src_key="nodes", dest_key="nodes"
        )
        pipeline.add_link(
            "input", "reranker", src_key="query_str", dest_key="query_str"
        )

    synthesizer = _build_synthesizer_module(
        response_mode=response_mode, model_id=model_id
    )
    pipeline.add_module("synthesizer", synthesizer)
    nodes_source = "reranker" if use_reranker else "retriever"
    pipeline.add_link(
        nodes_source, "synthesizer", src_key="nodes", dest_key="nodes"
    )
    pipeline.add_link(
        "input", "synthesizer", src_key="query_str", dest_key="query_str"
    )

    return pipeline


PIPELINE_DIR = None


def _get_pipeline_dir():
    global PIPELINE_DIR
    if PIPELINE_DIR is None:
        from pathlib import Path
        PIPELINE_DIR = Path.home() / ".llamaindex" / "pipelines"
        PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
    return PIPELINE_DIR


def save_pipeline(pipeline: Any, name: str):
    import json
    path = _get_pipeline_dir() / f"{name}.json"
    config = {
        "name": name,
        "modules": list(pipeline.module_dict.keys()),
        "verbose": pipeline.verbose,
    }
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
    logger.info(f"Pipeline saved: {path}")


def list_pipelines() -> List[str]:
    return [p.stem for p in _get_pipeline_dir().glob("*.json")]
