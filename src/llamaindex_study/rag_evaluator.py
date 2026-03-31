"""
RAG Evaluation Framework

提供 RAG 系统评估能力，基于 Ragas 指标：

评估维度：
1. Context Precision（上下文精确度）
2. Answer Relevancy（答案相关性）
3. Faithfulness（忠实度）
4. Context Recall（上下文召回率）

用法:
    from llamaindex_study.rag_evaluator import RAGEvaluator

    evaluator = RAGEvaluator()
    results = evaluator.evaluate(
        questions=["问题1", "问题2"],
        contexts=[["上下文1"], ["上下文2"]],
        answers=["答案1", "答案2"],
        ground_truths=["标准答案1", "标准答案2"],
    )
"""

from typing import Any, Dict, List, Optional

from llamaindex_study.config import get_settings


def check_ragas_available() -> bool:
    """检查 Ragas 是否已安装"""
    try:
        import ragas

        return True
    except ImportError:
        return False


def get_llm_for_evaluation() -> Any:
    """获取用于评估的 LLM"""
    from llamaindex_study.ollama_utils import configure_llamaindex_for_siliconflow

    configure_llamaindex_for_siliconflow()

    from llama_index.llms.openai import OpenAI

    settings = get_settings()

    return OpenAI(
        model=settings.siliconflow_model,
        api_key=settings.siliconflow_api_key,
        api_base=settings.siliconflow_base_url,
        temperature=0,
    )


def get_embed_model_for_evaluation() -> Any:
    """获取用于评估的 Embedding 模型"""
    from llama_index.embeddings.ollama import OllamaEmbedding

    settings = get_settings()

    return OllamaEmbedding(
        model_name=settings.ollama_embed_model,
        base_url=settings.ollama_base_url,
    )


class RAGEvaluator:
    """
    RAG 评估器

    使用 Ragas 框架评估 RAG 系统性能
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        embed_model: Optional[Any] = None,
    ):
        """
        初始化评估器

        Args:
            llm: 用于评估的 LLM（默认使用配置的 SiliconFlow LLM）
            embed_model: 用于评估的 Embedding 模型
        """
        self.llm = llm or get_llm_for_evaluation()
        self.embed_model = embed_model or get_embed_model_for_evaluation()
        self._ragas_available = check_ragas_available()

        if not self._ragas_available:
            import warnings

            warnings.warn("Ragas 未安装，评估功能不可用。请运行: uv add ragas")

    def evaluate(
        self,
        questions: List[str],
        contexts: List[List[str]],
        answers: List[str],
        ground_truths: List[str],
    ) -> Dict[str, Any]:
        """
        评估 RAG 系统

        Args:
            questions: 问题列表
            contexts: 上下文列表（每个问题对应的检索结果）
            answers: 生成的答案列表
            ground_truths: 标准答案列表

        Returns:
            评估结果字典
        """
        if not self._ragas_available:
            return {
                "error": "Ragas not installed",
                "message": "请运行: uv add ragas",
            }

        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        )
        from datasets import Dataset

        dataset = Dataset.from_dict(
            {
                "user_input": questions,
                "retrieved_contexts": contexts,
                "response": answers,
                "reference": ground_truths,
            }
        )

        metrics = [
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ]

        result = evaluate(
            dataset,
            metrics=metrics,
            llm=self.llm,
            embeddings=self.embed_model,
        )

        return result

    def evaluate_single(
        self,
        question: str,
        context: List[str],
        answer: str,
        ground_truth: str,
    ) -> Dict[str, float]:
        """评估单个问题"""
        return self.evaluate(
            questions=[question],
            contexts=[context],
            answers=[answer],
            ground_truths=[ground_truth],
        )

    def generate_test_dataset(
        self,
        documents: List[str],
        num_questions_per_doc: int = 3,
    ) -> List[Dict[str, str]]:
        """
        从文档生成测试数据集

        用 LLM 根据文档内容生成问答对

        Args:
            documents: 文档列表
            num_questions_per_doc: 每个文档生成的问题数量

        Returns:
            包含 question, answer, context 的字典列表
        """
        llm = get_llm_for_evaluation()

        results = []

        for doc in documents:
            prompt = f"""根据以下文档内容，生成 {num_questions_per_doc} 个问答对。

要求：
1. 问题覆盖文档的核心内容
2. 答案从文档中提取
3. 用中文输出
4. 格式：问题|答案

文档：
{doc[:2000]}

问答对："""

            response = llm.complete(prompt)
            text = str(response)

            for line in text.split("\n"):
                if "|" in line:
                    parts = line.split("|", 1)
                    if len(parts) == 2:
                        results.append(
                            {
                                "question": parts[0].strip(),
                                "answer": parts[1].strip(),
                                "context": doc,
                            }
                        )

        return results


class RAGMetrics:
    """
    RAG 评估指标说明

    各个指标的含义和优化方向：
    """

    METRICS = {
        "faithfulness": {
            "name": "忠实度",
            "description": "答案是否忠实于检索到的上下文，没有幻觉",
            "good_range": "> 0.8",
            "bad_range": "< 0.5",
            "优化方向": "提高检索质量，使用更相关的上下文",
        },
        "answer_relevancy": {
            "name": "答案相关性",
            "description": "答案是否针对问题，是否完整",
            "good_range": "> 0.7",
            "bad_range": "< 0.4",
            "优化方向": "优化 Prompt，提高答案针对性",
        },
        "context_precision": {
            "name": "上下文精确度",
            "description": "检索到的上下文是否都是相关的",
            "good_range": "> 0.7",
            "bad_range": "< 0.4",
            "优化方向": "使用更好的检索策略，启用 Reranker",
        },
        "context_recall": {
            "name": "上下文召回率",
            "description": "相关上下文是否都被检索到",
            "good_range": "> 0.7",
            "bad_range": "< 0.4",
            "优化方向": "增加 top_k，使用混合搜索",
        },
    }

    @classmethod
    def get_metrics_info(cls) -> Dict[str, Dict[str, str]]:
        """获取各指标详细信息"""
        return cls.METRICS
