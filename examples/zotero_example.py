#!/usr/bin/env python3
"""
Zotero 集成示例

演示如何使用 ZoteroReader 加载文献、标注和笔记。

用法:
    uv run python examples/zotero_example.py


需要配置 ZOTERO_DATA_DIR 环境变量:
    export ZOTERO_DATA_DIR=~/Zotero
"""

import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv

load_dotenv()

from kb.zotero_reader import (
    ZoteroReader,
    ZoteroClassifier,
    create_zotero_reader,
    DEFAULT_ZOTERO_DATA_DIR,
)


def example_statistics():
    """统计信息示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 1: Zotero 统计信息")
    print("=" * 60)

    reader = create_zotero_reader()
    stats = reader.get_statistics()

    print(f"\n📊 总体统计:")
    print(f"   文献总数: {stats['total_items']}")
    print(f"   标注总数: {stats['total_annotations']}")
    print(f"   笔记总数: {stats['total_notes']}")
    print(f"   收藏夹数: {stats['total_collections']}")

    print(f"\n📚 文献类型分布:")
    for item in stats["items_by_type"]:
        print(f"   {item['type']}: {item['count']}")

    reader.close()


def example_collections():
    """收藏夹示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 2: 收藏夹列表")
    print("=" * 60)

    reader = create_zotero_reader()
    collections = reader.get_collections()

    print(f"\n共 {len(collections)} 个收藏夹:\n")

    # 显示前20个
    for col in collections[:20]:
        parent = f" (父级: {col['parent_id']})" if col['parent_id'] else ""
        print(f"   [{col['id']}] {col['name']}{parent}")

    if len(collections) > 20:
        print(f"   ... 还有 {len(collections) - 20} 个")

    reader.close()


def example_load_collection():
    """加载收藏夹文献示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 3: 加载收藏夹文献")
    print("=" * 60)

    reader = create_zotero_reader()

    # 营养饲料理论 (collection_id = 8)
    print("\n📂 加载'营养饲料理论'收藏夹 (ID=8):\n")

    items = reader.load_items(collection_id=8, limit=10)

    print(f"找到 {len(items)} 篇文献\n")

    for i, item in enumerate(items, 1):
        print(f"{i}. {item.title}")
        print(f"   作者: {', '.join(item.creators[:2]) if item.creators else '未知'}")
        print(f"   类型: {item.item_type}")
        if item.tags:
            print(f"   标签: {', '.join(item.tags[:3])}")
        if item.annotations:
            print(f"   标注数: {len(item.annotations)}")
        if item.notes:
            print(f"   笔记数: {len(item.notes)}")
        print()

    reader.close()


def example_annotations():
    """标注示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 4: 查看标注内容")
    print("=" * 60)

    reader = create_zotero_reader()

    # 加载文献
    items = reader.load_items(collection_id=8, limit=5)

    # 找有标注的文献
    items_with_annotations = [item for item in items if item.annotations]

    print(f"\n前 {len(items)} 篇文献中有 {len(items_with_annotations)} 篇有标注\n")

    for item in items_with_annotations[:3]:
        print(f"📚 {item.title}")
        print(f"   标注数: {len(item.annotations)}")
        for ann in item.annotations[:3]:
            print(f"   📄 页{ann['page']}: {ann['text'][:80]}...")
            if ann['comment']:
                print(f"   💬 {ann['comment']}")
        print()

    reader.close()


def example_as_documents():
    """转换为 LlamaIndex Document 示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 5: 转换为 LlamaIndex Document")
    print("=" * 60)

    reader = create_zotero_reader()

    docs = reader.load_as_documents(collection_id=8, limit=3)

    print(f"\n转换为 {len(docs)} 个 Document\n")

    for i, doc in enumerate(docs, 1):
        print(f"文档 {i}: {doc.metadata['title'][:50]}...")
        print(f"   文本长度: {len(doc.text)} 字符")
        print(f"   标注数: {doc.metadata['annotation_count']}")
        print(f"   笔记数: {doc.metadata['note_count']}")
        print()

    reader.close()


def example_search():
    """搜索示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 6: 搜索文献")
    print("=" * 60)

    reader = create_zotero_reader()

    # 搜索关键词
    search_terms = ["猪", "营养", "饲料", "fiber", "低蛋白"]

    for term in search_terms:
        items = reader.load_items(search_query=term, limit=5)
        print(f"\n🔍 搜索 '{term}': {len(items)} 篇")

        for item in items[:3]:
            print(f"   • {item.title[:50]}...")

    reader.close()


def example_classification():
    """分类示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 7: 文献分类")
    print("=" * 60)

    reader = create_zotero_reader()
    classifier = ZoteroClassifier(reader)

    # 加载一些文献
    items = reader.load_items(collection_id=8, limit=5)

    print(f"\n对 {len(items)} 篇文献进行分类:\n")

    for item in items:
        matches = classifier.classify(item)
        print(f"📄 {item.title[:50]}...")
        print(f"   收藏夹: {', '.join(item.collections)}")
        print(f"   分类: {matches if matches else '无匹配'}")
        print()

    reader.close()


def main():
    print("\n" + "🎯" * 20)
    print("Zotero 集成示例")
    print("🎯" * 20)

    # 检查 Zotero 数据目录
    zotero_dir = os.getenv("ZOTERO_DATA_DIR", DEFAULT_ZOTERO_DATA_DIR)
    print(f"\n📁 Zotero 数据目录: {zotero_dir}")

    if not Path(zotero_dir).exists():
        print(f"❌ 目录不存在: {zotero_dir}")
        print("请设置 ZOTERO_DATA_DIR 环境变量")
        return

    # 示例 1: 统计信息
    example_statistics()

    # 示例 2: 收藏夹
    example_collections()

    # 示例 3: 加载收藏夹文献
    example_load_collection()

    # 示例 4: 标注
    example_annotations()

    # 示例 5: 转换为 Document
    example_as_documents()

    # 示例 6: 搜索
    example_search()

    # 示例 7: 分类
    example_classification()

    print("\n" + "=" * 60)
    print("✨ 示例完成！")
    print("=" * 60)

    print("""
📌 使用说明:

1. 设置环境变量（可选）:
   export ZOTERO_DATA_DIR=~/Zotero

2. 加载收藏夹文献:
   from kb.zotero_reader import create_zotero_reader

   reader = create_zotero_reader()
   items = reader.load_items(collection_id=8)  # 营养饲料理论
   docs = reader.load_as_documents(collection_id=8)  # 作为 Document

3. 搜索文献:
   items = reader.load_items(search_query="猪营养")

4. 获取单个文献:
   item = reader.get_item(item_id=123)
""")


if __name__ == "__main__":
    main()
