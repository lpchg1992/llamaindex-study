#!/usr/bin/env python3
"""
文档处理示例 - 最佳实践版

演示智能文档处理的最佳实践：
1. 基于 Token 的切分（而非字符）
2. 多种切分策略：语义、Markdown标题、句子
3. 自动推荐切分参数

用法:
    poetry run python examples/document_processing_example.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llamaindex_study.reader import (
    DocumentReader,
    SmartDocumentProcessor,
    ChunkStrategy,
    ChunkConfig,
    load_and_split,
    estimate_tokens,
    recommend_chunk_size,
)


def example_basic_loading():
    """基础文档加载"""
    print("\n" + "=" * 60)
    print("🚀 示例 1: 基础文档加载")
    print("=" * 60)

    reader = DocumentReader(input_dir="./data")
    documents = reader.load()

    print(f"\n📄 加载了 {len(documents)} 个文档")
    for doc in documents:
        tokens = estimate_tokens(doc.text)
        print(f"   - {doc.metadata.get('file_name', 'unknown')}: {len(doc.text)} 字符 ≈ {tokens} tokens")


def example_markdown_parsing():
    """Markdown 标题感知切分"""
    print("\n" + "=" * 60)
    print("🚀 示例 2: Markdown 标题感知切分")
    print("=" * 60)

    # 创建 Markdown 处理器
    processor = SmartDocumentProcessor.for_markdown(chunk_size=200, chunk_overlap=20)

    # 加载所有文件，然后筛选 Markdown
    reader = DocumentReader(input_dir="./data")
    documents = reader.load()

    # 筛选 Markdown 文档
    md_docs = [doc for doc in documents if doc.metadata.get('file_name', '').endswith('.md')]

    if md_docs:
        # 按 Markdown 标题切分
        nodes = processor.process_documents(md_docs, show_progress=False)

        print(f"\n📄 处理了 {len(md_docs)} 个 Markdown 文档")
        print(f"   切分后: {len(nodes)} 个节点")

        for i, node in enumerate(nodes[:5]):
            # 显示标题层级信息
            header_path = node.metadata.get("header_path", "N/A")
            print(f"\n   节点 {i+1} (标题层级: {header_path}):")
            print(f"   内容: {node.text[:100]}...")
    else:
        print("\n   ⚠️  未找到 Markdown 文件，跳过此示例")


def example_semantic_chunking():
    """语义切分（推荐）"""
    print("\n" + "=" * 60)
    print("🚀 示例 3: 语义切分（推荐）")
    print("=" * 60)

    # 创建语义切分处理器
    processor = SmartDocumentProcessor.for_semantic(
        chunk_size=300,
        chunk_overlap=30,
        similarity_threshold=0.5,
    )

    reader = DocumentReader(input_dir="./data")
    documents = reader.load()

    if documents:
        # 语义切分
        nodes = processor.process_documents(documents, show_progress=False)

        print(f"\n📄 处理了 {len(documents)} 个文档")
        print(f"   语义切分后: {len(nodes)} 个节点")

        for i, node in enumerate(nodes[:3]):
            print(f"\n   节点 {i+1}:")
            print(f"   内容: {node.text[:150]}...")


def example_pdf_processing():
    """PDF 处理"""
    print("\n" + "=" * 60)
    print("🚀 示例 4: PDF 处理")
    print("=" * 60)

    pdf_path = Path("./data/sample.pdf")
    if not pdf_path.exists():
        print(f"   ⚠️  PDF 文件不存在: {pdf_path}")
        return

    # 获取 PDF 信息
    info = SmartDocumentProcessor.get_pdf_info(pdf_path)
    print(f"\n📄 PDF 信息:")
    print(f"   页数: {info['num_pages']}")
    print(f"   大小: {info.get('file_size_mb', 0)} MB")

    # 处理 PDF（按页加载）
    docs = SmartDocumentProcessor.process_pdf(pdf_path)
    print(f"\n   加载了 {len(docs)} 页")

    # 切分
    processor = SmartDocumentProcessor.for_pdf(chunk_size=256, chunk_overlap=25)
    nodes = processor.process_documents(docs, show_progress=False)
    print(f"   切分后: {len(nodes)} 个节点")

    if nodes:
        print(f"\n   节点 1 ({len(nodes[0].text)} 字符):")
        print(f"   {nodes[0].text[:150]}...")


def example_configuration():
    """配置化切分"""
    print("\n" + "=" * 60)
    print("🚀 示例 5: 配置化切分")
    print("=" * 60)

    # 创建自定义配置
    config = ChunkConfig(
        chunk_size=400,
        chunk_overlap=40,
        strategy=ChunkStrategy.MARKDOWN,
        header_path_separator=" > ",
    )

    processor = SmartDocumentProcessor(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        strategy=config.strategy,
    )

    reader = DocumentReader(input_dir="./data")
    documents = reader.load()

    if documents:
        nodes = processor.process_documents(documents, show_progress=False)
        print(f"\n📄 配置: chunk_size={config.chunk_size}, overlap={config.chunk_overlap}")
        print(f"   策略: {config.strategy.value}")
        print(f"   结果: {len(nodes)} 个节点")


def example_recommendation():
    """自动推荐切分参数"""
    print("\n" + "=" * 60)
    print("🚀 示例 6: 自动推荐切分参数")
    print("=" * 60)

    # 测试不同长度
    test_lengths = [500, 2000, 10000]

    for length in test_lengths:
        rec = recommend_chunk_size(length, is_markdown=True)
        tokens = estimate_tokens("中" * length)
        print(f"\n   文档长度: {length} 字符 (≈ {tokens} tokens)")
        print(f"   推荐: chunk_size={rec['chunk_size']}, overlap={rec['chunk_overlap']}")
        print(f"   策略: {rec['strategy'].value}")
        print(f"   说明: {rec['note']}")


def example_token_estimation():
    """Token 估算"""
    print("\n" + "=" * 60)
    print("🚀 示例 7: Token 估算")
    print("=" * 60)

    test_texts = [
        "这是一段中文文本",
        "This is an English text with some words.",
        "混合文本 Chinese and English 混合在一起",
    ]

    for text in test_texts:
        tokens = estimate_tokens(text)
        print(f"\n   文本: {text}")
        print(f"   字符数: {len(text)}, 估算 tokens: {tokens}")


def main():
    print("\n" + "🎯" * 20)
    print("文档处理示例 - 最佳实践版")
    print("🎯" * 20)

    # 示例 1: 基础加载
    example_basic_loading()

    # 示例 2: Markdown 标题切分
    example_markdown_parsing()

    # 示例 3: 语义切分
    example_semantic_chunking()

    # 示例 4: PDF 处理
    example_pdf_processing()

    # 示例 5: 配置化切分
    example_configuration()

    # 示例 6: 自动推荐
    example_recommendation()

    # 示例 7: Token 估算
    example_token_estimation()

    print("\n" + "=" * 60)
    print("✨ 示例完成！")
    print("=" * 60)

    print("""
📌 最佳实践总结:

1. chunk_size 使用 token 而非字符
   - 推荐 256-512 tokens
   - 太小丢失上下文，太大检索不精准

2. chunk_overlap 保持 10-20%
   - 512 tokens → 50-100 tokens 重叠
   - 保持跨块内容连续性

3. 选择合适的切分策略:
   - SEMANTIC: 语义切分（推荐，最智能）
   - MARKDOWN: 按标题切分（适合 Markdown 文档）
   - SENTENCE: 按句子切分（通用）

4. PDF 处理:
   - 先按页加载，再根据内容切分
   - 保留页码元数据
""")


if __name__ == "__main__":
    main()
