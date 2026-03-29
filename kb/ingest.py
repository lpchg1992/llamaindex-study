#!/usr/bin/env python3
"""
知识库导入脚本

将 Obsidian 文档导入到各个知识库的向量索引中。
使用小批量增量处理+定期保存，避免 Ollama 过载断开。

用法:
    python -m kb.ingest                    # 导入所有知识库
    python -m kb.ingest --list            # 列出所有知识库状态
    python -m kb.ingest --kb swine_nutrition  # 只导入指定知识库
    python -m kb.ingest --rebuild          # 重建所有知识库
"""

import argparse
import sys
import time
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from kb.registry import KnowledgeBaseRegistry
from kb.obsidian_reader import ObsidianReader
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


def configure_embed_model():
    """配置全局 Embedding 模型"""
    from llama_index.core import Settings
    from llama_index.embeddings.ollama import OllamaEmbedding

    Settings.embed_model = OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )
    Settings.chunk_size = 1024
    Settings.embed_batch_size = 3  # 极小批量


def build_index_incremental(documents, persist_dir, show_progress=False, max_retries=5):
    """
    使用小批量增量构建索引，每批处理后保存中间结果
    避免 Ollama 一次性处理过多文档导致断开
    """
    from llama_index.core import VectorStoreIndex, StorageContext
    from llama_index.core.node_parser import SentenceSplitter

    node_parser = SentenceSplitter(chunk_size=1024, chunk_overlap=50)

    # 分批处理文档
    batch_size = 10  # 每批 10 个文档
    batches = [documents[i:i+batch_size] for i in range(0, len(documents), batch_size)]

    print(f"   📦 共 {len(documents)} 文档，分 {len(batches)} 批处理")

    index = None
    total_nodes = 0

    for batch_idx, batch in enumerate(batches):
        print(f"   处理批次 {batch_idx+1}/{len(batches)} ({len(batch)} 文档)...", end="", flush=True)

        # 切分文档为节点
        batch_nodes = []
        for doc in batch:
            nodes = node_parser.get_nodes_from_documents([doc])
            batch_nodes.extend(nodes)

        # 构建或扩展索引
        for attempt in range(max_retries):
            try:
                if index is None:
                    # 第一批：创建索引
                    index = VectorStoreIndex(batch_nodes, show_progress=False)
                else:
                    # 后续批次：增量添加节点
                    index.insert_nodes(batch_nodes)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 10
                    print(f"\n      ⚠️ 批次 {batch_idx+1} 失败，{wait_time}秒后重试 ({attempt+1}/{max_retries})")
                    logger.warning(f"批次 {batch_idx+1} 失败，将重试: {e}")
                    time.sleep(wait_time)
                else:
                    print(f"\n      ❌ 批次 {batch_idx+1} 最终失败: {e}")
                    logger.error(f"批次 {batch_idx+1} 最终失败: {e}")
                    raise

        total_nodes += len(batch_nodes)
        print(f" -> 累计节点: {total_nodes}")

        # 每2批保存一次中间结果
        if (batch_idx + 1) % 2 == 0:
            print(f"      💾 保存中间结果...")
            index.storage_context.persist(persist_dir=str(persist_dir))

    # 最终保存
    print(f"   💾 保存最终索引...")
    index.storage_context.persist(persist_dir=str(persist_dir))

    return index, total_nodes


def ingest_kb(kb_id: str, rebuild: bool = False, verbose: bool = False) -> bool:
    """导入单个知识库"""
    registry = KnowledgeBaseRegistry()
    kb = registry.get(kb_id)

    if kb is None:
        print(f"❌ 知识库不存在: {kb_id}")
        logger.error(f"知识库不存在: {kb_id}")
        return False

    if registry.is_indexed(kb_id) and not rebuild:
        print(f"⏭️  {kb.name} 已有索引，跳过（使用 --rebuild 重建）")
        return True

    print(f"\n📚 开始导入: {kb.name}")
    print(f"   描述: {kb.description}")
    print(f"   标签: {', '.join(kb.tags)}")

    kb.persist_dir.mkdir(parents=True, exist_ok=True)

    # 加载文档
    all_docs = []
    vault_root = Path.home() / "Documents" / "Obsidian Vault"

    for source_path in kb.source_paths_abs(vault_root):
        if not source_path.exists():
            print(f"⚠️  路径不存在，跳过: {source_path}")
            logger.warning(f"路径不存在: {source_path}")
            continue

        rel_path = str(source_path.relative_to(vault_root))
        print(f"\n   📂 读取: {rel_path}")

        reader = ObsidianReader(input_dir=source_path, recursive=True)
        docs = reader.load()

        print(f"      ✅ 加载 {len(docs)} 个文档")
        all_docs.extend(docs)

    if not all_docs:
        print(f"❌ 没有找到文档: {kb.name}")
        logger.error(f"没有找到文档: {kb.name}")
        return False

    print(f"\n   📊 共 {len(all_docs)} 个文档")

    configure_embed_model()

    start_time = time.time()

    try:
        index, node_count = build_index_incremental(
            all_docs,
            persist_dir=kb.persist_dir,
            show_progress=verbose,
        )
    except Exception as e:
        print(f"❌ 索引构建最终失败: {e}")
        logger.error(f"索引构建失败: {e}", exc_info=True)
        return False

    elapsed = time.time() - start_time

    print(f"\n   ✅ 索引已保存: {kb.persist_dir}")
    print(f"   ⏱️  耗时: {elapsed:.1f}秒")
    print(f"   📝 文档数: {len(all_docs)}, 节点数: {node_count}")
    
    logger.info(f"知识库 {kb_id} 导入完成: {len(all_docs)} 文档, {node_count} 节点, 耗时 {elapsed:.1f}秒")

    return True


def list_knowledge_bases():
    """列出所有知识库及其状态"""
    registry = KnowledgeBaseRegistry()

    print("\n📚 知识库列表\n")
    print(f"{'ID':<20} {'名称':<20} {'状态':<10}")
    print("-" * 55)

    for kb in registry.list_all():
        status = "✅ 已索引" if registry.is_indexed(kb.id) else "⏳ 未索引"
        print(f"{kb.id:<20} {kb.name:<20} {status:<10}")

    print()


def main():
    parser = argparse.ArgumentParser(description="知识库导入工具")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有知识库")
    parser.add_argument("--kb", "-k", type=str, help="指定知识库 ID")
    parser.add_argument("--rebuild", "-r", action="store_true", help="重建已有索引")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")

    args = parser.parse_args()

    registry = KnowledgeBaseRegistry()

    if args.list:
        list_knowledge_bases()
        return

    if args.kb:
        success = ingest_kb(args.kb, rebuild=args.rebuild, verbose=args.verbose)
        sys.exit(0 if success else 1)
    else:
        print("🚀 开始批量导入所有知识库\n")
        success_count = 0
        fail_count = 0

        for kb in registry.list_all():
            if ingest_kb(kb.id, rebuild=args.rebuild, verbose=args.verbose):
                success_count += 1
            else:
                fail_count += 1

        print(f"\n\n🎉 导入完成: {success_count} 成功, {fail_count} 失败")
        
        if fail_count > 0:
            logger.warning(f"批量导入完成: {success_count} 成功, {fail_count} 失败")
        else:
            logger.info(f"批量导入完成: {success_count} 成功")


if __name__ == "__main__":
    main()
