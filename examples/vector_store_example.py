#!/usr/bin/env python3
"""
向量数据库使用示例

演示如何使用不同的向量数据库：
1. LanceDB（默认，推荐）
2. Chroma
3. Qdrant

用法:
    uv run python examples/vector_store_example.py
"""

import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llamaindex_study.vector_store import (
    VectorStoreType,
    create_vector_store,
    get_default_vector_store,
)
from llamaindex_study.config import get_settings
from llamaindex_study.reader import DocumentReader


def example_lancedb():
    """LanceDB 示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 1: LanceDB 向量数据库")
    print("=" * 60)

    # 1. 创建向量存储
    persist_dir = Path("/volumes/online/llamaindex/storage_lancedb")
    vector_store = get_default_vector_store(persist_dir=persist_dir)
    vector_store.table_name = "example_table"

    print(f"存储目录: {persist_dir}")
    print(f"表名: {vector_store.table_name}")

    # 2. 检查是否已有索引
    if vector_store.exists():
        print("✅ 索引已存在，加载中...")
        index = vector_store.load_index()
    else:
        # 3. 加载文档
        data_dir = Path(__file__).parent.parent / "data"
        reader = DocumentReader(input_dir=data_dir, required_exts=[".txt", ".md"])
        documents = reader.load()
        
        if not documents:
            print("📂 没有找到文档，跳过构建")
            return
            
        print(f"📄 加载了 {len(documents)} 个文档")

        # 4. 构建索引
        print("🔨 构建索引...")
        index = vector_store.build_index(documents)

    # 5. 统计信息
    print("\n📊 统计信息:")
    stats = vector_store.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")


def example_chroma():
    """Chroma 示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 2: Chroma 向量数据库")
    print("=" * 60)

    # 1. 创建向量存储
    persist_dir = Path("./storage_chroma")
    vector_store = create_vector_store(
        store_type=VectorStoreType.CHROMA,
        persist_dir=persist_dir,
        collection_name="my_collection",
    )

    print(f"存储目录: {persist_dir}")
    print(f"集合名: {vector_store.collection_name}")

    # 2. 检查是否已有索引
    if vector_store.exists():
        print("✅ 索引已存在，加载中...")
        index = vector_store.load_index()
    else:
        # 3. 加载文档
        data_dir = Path(__file__).parent.parent / "data"
        reader = DocumentReader(input_dir=data_dir, required_exts=[".txt", ".md"])
        documents = reader.load()
        
        if not documents:
            print("📂 没有找到文档，跳过构建")
            return
            
        print(f"📄 加载了 {len(documents)} 个文档")

        # 4. 构建索引
        print("🔨 构建索引...")
        index = vector_store.build_index(documents)

    # 5. 统计信息
    print("\n📊 统计信息:")
    stats = vector_store.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")


def example_switch_stores():
    """切换向量数据库示例"""
    print("\n" + "=" * 60)
    print("🚀 示例 3: 切换不同的向量数据库")
    print("=" * 60)

    # 定义不同的向量存储配置
    stores = {
        "LanceDB": {
            "type": VectorStoreType.LANCEDB,
            "persist_dir": Path("/volumes/online/llamaindex/storage_lancedb"),
            "table_name": "example_table",
        },
        "Chroma": {
            "type": VectorStoreType.CHROMA,
            "persist_dir": Path("/volumes/online/llamaindex/storage_chroma"),
            "collection_name": "example_table",
        },
    }

    for name, config in stores.items():
        print(f"\n📦 测试 {name}:")
        vector_store = create_vector_store(
            store_type=config["type"],
            persist_dir=config["persist_dir"],
            **{k: v for k, v in config.items() if k not in ["type", "persist_dir"]}
        )

        exists = vector_store.exists()
        print(f"   存在: {exists}")

        if exists:
            stats = vector_store.get_stats()
            print(f"   记录数: {stats.get('row_count', 'N/A')}")


def main():
    print("\n" + "🎯" * 20)
    print("向量数据库使用示例")
    print("🎯" * 20)

    # 示例 1: LanceDB（推荐）
    try:
        example_lancedb()
    except Exception as e:
        print(f"❌ LanceDB 示例失败: {e}")
        import traceback
        traceback.print_exc()

    # 示例 2: Chroma（可选）
    # try:
    #     example_chroma()
    # except Exception as e:
    #     print(f"❌ Chroma 示例失败: {e}")

    # 示例 3: 切换存储
    try:
        example_switch_stores()
    except Exception as e:
        print(f"❌ 切换存储示例失败: {e}")

    print("\n" + "=" * 60)
    print("✨ 示例完成！")
    print("=" * 60)
    print("""
📌 使用建议:

1. 个人项目/小规模数据（< 100万向量）:
   → 推荐 LanceDB（默认），性能优异，本地部署

2. 需要快速原型:
   → Chroma，简单易用

3. 生产环境/大规模数据:
   → Qdrant 或云端向量服务（Pinecone/Milvus）

4. 切换向量数据库:
   → 修改 .env 中的 VECTOR_STORE_TYPE 配置
   → 或在代码中指定 create_vector_store(store_type=...)
""")


if __name__ == "__main__":
    main()
