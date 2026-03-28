#!/usr/bin/env python3
"""
LlamaIndex Study - 示例脚本

展示 LlamaIndex 的基本用法：
1. 加载文档
2. 构建索引
3. 执行查询
4. 检索相关文档

使用方法：
    poetry run python example.py
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from llamaindex_study.config import get_settings
from llamaindex_study.reader import DocumentReader
from llamaindex_study.index_builder import IndexBuilder
from llamaindex_study.query_engine import QueryEngineWrapper


def print_section(title: str) -> None:
    """打印分节标题"""
    print(f"\n{'=' * 60}")
    print(f"📖 {title}")
    print("=" * 60)


def example_basic_query() -> None:
    """基本查询示例"""
    print_section("示例 1: 基本查询")

    # 获取配置
    settings = get_settings()
    print(f"使用 LLM: {settings.siliconflow_model}")
    print(f"使用 Embedding: {settings.ollama_embed_model}")

    # 文档目录
    data_dir = Path(__file__).parent / "data"

    # 1. 加载文档
    print("\n步骤 1: 加载文档")
    reader = DocumentReader(input_dir=data_dir)
    documents = reader.load()
    print(f"   - 加载了 {len(documents)} 个文档")

    # 2. 构建索引
    print("\n步骤 2: 构建索引")
    builder = IndexBuilder(persist_dir=Path(settings.persist_dir))
    index = builder.build_from_documents(documents)
    print("   - 索引构建完成")

    # 3. 创建查询引擎
    print("\n步骤 3: 创建查询引擎")
    query_engine = QueryEngineWrapper(index)
    print("   - 查询引擎创建完成")

    # 4. 执行查询
    print("\n步骤 4: 执行查询")
    questions = [
        "LlamaIndex 是什么？",
        "LlamaIndex 有哪些核心概念？",
        "如何快速开始使用 LlamaIndex？",
    ]

    for question in questions:
        print(f"\n   问题: {question}")
        response = query_engine.query(question)
        print(f"   回答: {response}")


def example_retrieval() -> None:
    """检索示例"""
    print_section("示例 2: 文档检索（不经过 LLM）")

    # 文档目录
    data_dir = Path(__file__).parent / "data"

    # 加载文档并构建索引
    reader = DocumentReader(input_dir=data_dir)
    documents = reader.load()
    builder = IndexBuilder()
    index = builder.build_from_documents(documents)

    # 创建查询引擎
    query_engine = QueryEngineWrapper(index)

    # 检索相关文档
    query = "LlamaIndex 的新特性"
    print(f"\n检索查询: {query}")
    print("\n相关文档片段:")

    nodes = query_engine.retrieve(query)
    for i, node in enumerate(nodes, 1):
        print(f"\n  [{i}] 相似度: {node.score:.4f}")
        # 打印前 200 个字符
        text_preview = node.text[:200] + "..." if len(node.text) > 200 else node.text
        print(f"      内容: {text_preview}")


def example_stream_output() -> None:
    """流式输出示例"""
    print_section("示例 3: 流式输出")

    # 文档目录
    data_dir = Path(__file__).parent / "data"

    # 加载文档并构建索引
    reader = DocumentReader(input_dir=data_dir)
    documents = reader.load()
    builder = IndexBuilder()
    index = builder.build_from_documents(documents)

    # 创建查询引擎
    query_engine = QueryEngineWrapper(index)

    # 执行流式查询
    query = "请介绍一下 LlamaIndex"
    print(f"\n问题: {query}")
    print("回答 (流式输出):\n   ", end="", flush=True)

    query_engine.query(query, stream=True)


def main() -> None:
    """主函数，运行所有示例"""
    print("\n" + "🌟" * 30)
    print(" LlamaIndex Study - 功能示例 ")
    print("🌟" * 30)

    # 示例 1: 基本查询
    example_basic_query()

    # 示例 2: 文档检索
    example_retrieval()

    # 示例 3: 流式输出
    example_stream_output()

    # 结束
    print_section("示例结束")
    print("\n✅ 所有示例执行完成！")
    print("\n了解更多：")
    print("   - 运行 'poetry run python main.py' 进入交互式查询")
    print("   - 查看 README.md 了解更多使用方法")
    print()


if __name__ == "__main__":
    main()
