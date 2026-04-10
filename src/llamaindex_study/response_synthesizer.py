"""
Response Synthesizer Configuration Module

配置 LlamaIndex 的 Response Synthesizer，控制答案生成策略：

1. compact (默认) - 合并小 chunk，减少 token 消耗
2. refine - 迭代精炼，逐步完善答案
3. tree_summarize - 树形汇总，适合多文档总结
4. simple_summarize - 简单总结，直接拼接

用法:
    from llamaindex_study.response_synthesizer import get_response_synthesizer

    synth = get_response_synthesizer(mode="compact")
    engine = RetrieverQueryEngine(retriever=retriever, response_synthesizer=synth)
"""

from typing import Any, Optional

from llamaindex_study.config import get_settings


class ResponseMode:
    COMPACT = "compact"
    REFINE = "refine"
    TREE_SUMMARIZE = "tree_summarize"
    SIMPLE = "simple"
    NO_TEXT = "no_text"
    ACCUMULATE = "accumulate"


def get_response_synthesizer(
    mode: str = "compact",
    verbose: bool = False,
    callback_manager: Optional[Any] = None,
) -> Any:
    """
    获取配置好的 Response Synthesizer

    Args:
        mode: 合成模式
            - compact: 合并小 chunk 后生成答案（默认，省 token）
            - refine: 迭代精炼，逐步完善（质量最高，token 消耗大）
            - tree_summarize: 树形汇总（适合多文档总结）
            - simple: 简单拼接后生成
            - no_text: 只检索不生成
            - accumulate: 对每个 chunk 分别处理后拼接
        verbose: 是否显示详细过程
        callback_manager: 回调管理器

    Returns:
        配置好的 Response Synthesizer
    """
    from llama_index.core.response_synthesizers import (
        CompactAndRefine,
        Refine,
        TreeSummarize,
        SimpleSummarize,
        Accumulate,
    )
    from llama_index.core.response_synthesizers.no_text import NoText

    mode = mode.lower()

    if mode == ResponseMode.COMPACT or mode == "compact":
        from llama_index.core.response_synthesizers import CompactAndRefine

        return CompactAndRefine(
            verbose=verbose,
            callback_manager=callback_manager,
        )
    elif mode == ResponseMode.REFINE or mode == "refine":
        return Refine(
            verbose=verbose,
            callback_manager=callback_manager,
        )
    elif mode == ResponseMode.TREE_SUMMARIZE or mode == "tree_summarize":
        return TreeSummarize(
            verbose=verbose,
            callback_manager=callback_manager,
        )
    elif mode == ResponseMode.SIMPLE or mode == "simple":
        return SimpleSummarize(
            verbose=verbose,
            callback_manager=callback_manager,
        )
    elif mode == ResponseMode.NO_TEXT or mode == "no_text":
        from llama_index.core.llms import MockLLM

        return NoText(llm=MockLLM())
    elif mode == ResponseMode.ACCUMULATE or mode == "accumulate":
        return Accumulate(
            verbose=verbose,
            callback_manager=callback_manager,
        )
    else:
        from llama_index.core.response_synthesizers import CompactAndRefine

        return CompactAndRefine(verbose=verbose, callback_manager=callback_manager)


def create_query_engine_with_synthesizer(
    retriever: Any,
    mode: str = "compact",
    **kwargs,
) -> Any:
    """
    创建使用指定 Response Synthesizer 的查询引擎

    Args:
        retriever: 检索器
        mode: 合成模式
        **kwargs: 额外参数传给 as_query_engine

    Returns:
        配置好的查询引擎
    """
    from llama_index.core.query_engine import RetrieverQueryEngine

    synth = get_response_synthesizer(mode=mode)

    return RetrieverQueryEngine(
        retriever=retriever,
        response_synthesizer=synth,
        **kwargs,
    )


def get_synthesizer_stats(mode: str) -> dict:
    """
    获取各合成模式的特点和适用场景

    Returns:
        包含各模式信息的字典
    """
    return {
        "compact": {
            "name": "Compact (默认)",
            "token_efficiency": "高",
            "answer_quality": "中",
            "speed": "快",
            "use_case": "日常问答，推荐使用",
        },
        "refine": {
            "name": "Refine (精炼)",
            "token_efficiency": "低",
            "answer_quality": "高",
            "speed": "慢",
            "use_case": "复杂问题，需要详细答案",
        },
        "tree_summarize": {
            "name": "Tree Summarize (树形汇总)",
            "token_efficiency": "中",
            "answer_quality": "高",
            "speed": "中",
            "use_case": "多文档总结，需要全面覆盖",
        },
        "simple": {
            "name": "Simple (简单)",
            "token_efficiency": "低",
            "answer_quality": "中",
            "speed": "快",
            "use_case": "简单问题，直接拼接",
        },
        "no_text": {
            "name": "No Text (仅检索)",
            "token_efficiency": "无",
            "answer_quality": "无",
            "speed": "最快",
            "use_case": "调试、查看检索结果",
        },
        "accumulate": {
            "name": "Accumulate (累积)",
            "token_efficiency": "中",
            "answer_quality": "中",
            "speed": "中",
            "use_case": "对每个 chunk 分别处理后拼接",
        },
    }
