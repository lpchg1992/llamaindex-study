#!/usr/bin/env python3
"""Reranker 独立测试脚本"""

from llamaindex_study.reranker import OllamaReranker


def test_reranker():
    """测试 Ollama Reranker"""

    reranker = OllamaReranker(
        model="dengcao/bge-reranker-v2-m3",
        base_url="http://localhost:11434",
        top_n=3,
    )

    query = "什么是猪营养学中的氨基酸平衡？"
    docs = [
        "猪营养学是研究猪的饲料和营养需求的科学，包括碳水化合物、蛋白质、维生素等营养素的合理配比。",
        "物理学是研究物质运动规律和能量转换的基础学科，主要包括力学、电磁学、热学等分支。",
        "氨基酸平衡是猪饲料配方中的关键指标，赖氨酸、蛋氨酸、苏氨酸等必需氨基酸需要科学配比才能提高饲料利用率。",
        "中国的经济发展在过去几十年中取得了举世瞩目的成就。",
        "在猪营养中，能量饲料和蛋白质饲料是最主要的两类饲料来源。",
    ]

    print(f"查询: {query}")
    print(f"文档数: {len(docs)}")
    print("---")

    scores = reranker._score_pairs(query, docs)
    for i, (doc, score) in enumerate(zip(docs, scores)):
        print(f"  [{i+1}] 分数: {score:.4f}")
        print(f"      {doc[:50]}...")
        print()


if __name__ == "__main__":
    test_reranker()
