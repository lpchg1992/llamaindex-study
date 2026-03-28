#!/usr/bin/env python3
"""
Obsidian 文档分类示例

演示如何使用 ObsidianClassifier 对文档进行分类：
1. 基于目录路径分类
2. 基于标签分类
3. 混合分类

用法:
    poetry run python examples/obsidian_classifier_example.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from kb.obsidian_reader import ObsidianReader, ObsidianClassifier
from kb.registry import KnowledgeBaseRegistry


def example_tag_extraction():
    """标签提取示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 1: 标签提取")
    print("=" * 60)

    test_contents = [
        """
        # 猪营养研究笔记

        本文研究猪的蛋白质需求。

        #猪营养 #蛋白质 #研究
        """,
        """
        # Python 编程指南

        学习 Python 基础语法。

        #python #编程 #AI工具
        """,
        """
        # 学术论文笔记

        关于深度学习的论文总结。

        tags: [学术, 论文, AI研究]
        """,
    ]

    for i, content in enumerate(test_contents, 1):
        tags = ObsidianReader.extract_tags(content)
        print(f"\n文档 {i}: {tags}")


def example_classification():
    """文档分类示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 2: 文档分类")
    print("=" * 60)

    # 创建分类器
    classifier = ObsidianClassifier()

    # 模拟文档
    test_docs = [
        # 路径匹配 + 标签匹配
        ("技术理论及方法/猪营养.md", ["#猪营养", "#饲料"]),
        ("试验研发/2024实验记录.md", ["#试验", "#研究"]),
        ("IT/Python指南.md", ["#python", "#编程"]),
        ("博士专项/论文笔记.md", ["#学术", "#论文"]),

        # 仅标签匹配（路径不在已知目录）
        ("随机文件夹/畜牧资讯.md", ["#畜牧", "#行业"]),
        ("未分类/AI工具使用.md", ["#AI工具"]),

        # 无匹配
        ("其他/杂项.md", ["#其他"]),
    ]

    print("\n📄 分类结果:\n")
    print(f"{'文件路径':<35} {'标签':<25} {'分类'}")
    print("-" * 80)

    for path, tags in test_docs:
        class MockDoc:
            def __init__(self, path, tags):
                self.metadata = {
                    "relative_path": path,
                    "obsidian_tags": tags,
                    "tags_list": [],
                }

        doc = MockDoc(path, tags)
        matches = classifier.classify(doc)

        # 获取知识库名称
        kb_names = []
        for kb_id in matches:
            kb = classifier.registry.get(kb_id)
            if kb:
                kb_names.append(kb.name)

        result = ", ".join(kb_names) if kb_names else "❌ 未分类"
        print(f"{path:<35} {str(tags):<25} {result}")


def example_knowledge_base_tags():
    """知识库标签配置示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 3: 知识库标签配置")
    print("=" * 60)

    registry = KnowledgeBaseRegistry()

    print("\n📚 知识库分类规则:\n")
    for kb in registry.list_all():
        print(f"{kb.name}:")
        print(f"   目录: {', '.join(kb.source_paths)}")
        print(f"   标签: {', '.join(kb.source_tags[:5])}{'...' if len(kb.source_tags) > 5 else ''}")
        print()


def main():
    print("\n" + "🎯" * 20)
    print("Obsidian 文档分类示例")
    print("🎯" * 20)

    # 示例 1: 标签提取
    example_tag_extraction()

    # 示例 2: 文档分类
    example_classification()

    # 示例 3: 知识库标签配置
    example_knowledge_base_tags()

    print("\n" + "=" * 60)
    print("✨ 示例完成！")
    print("=" * 60)
    print("""
📌 分类规则说明:

1. 目录路径匹配:
   - 文档所在目录包含知识库的 source_paths 时匹配
   - 例如: "技术理论及方法/*" 匹配猪营养库

2. 标签匹配:
   - 文档的 #标签 与知识库的 source_tags 匹配
   - 支持精确匹配和包含匹配
   - 例如: #猪营养 匹配 source_tags 中的 #猪营养

3. 混合匹配:
   - 文档可以同时属于多个知识库
   - 路径匹配和标签匹配的并集
""")


if __name__ == "__main__":
    main()
