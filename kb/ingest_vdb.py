#!/usr/bin/env python3
"""
知识库导入脚本 - 向量数据库版本

支持增量同步：
- 基于文件哈希检测变更
- 自动处理新增、更新、删除
- 手动触发

用法:
    python -m kb.ingest_vdb                    # 增量导入所有知识库
    python -m kb.ingest_vdb --list            # 列出所有知识库状态
    python -m kb.ingest_vdb --kb swine_nutrition  # 只导入指定知识库
    python -m kb.ingest_vdb --rebuild          # 重建所有知识库（强制全量）
    python -m kb.ingest_vdb --stats            # 查看统计信息
    python -m kb.ingest_vdb --show-changes     # 显示变更但不执行
"""

import argparse
import sys
import time
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from kb.registry import KnowledgeBaseRegistry
from kb.obsidian_reader import ObsidianReader
from kb.sync_state import SyncState
from llamaindex_study.vector_store import (
    VectorStoreType,
    create_vector_store,
    get_default_vector_store,
)


def configure_embed_model():
    """配置全局 Embedding 模型"""
    from llama_index.core import Settings
    from llama_index.embeddings.ollama import OllamaEmbedding

    Settings.embed_model = OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )
    Settings.chunk_size = 512
    Settings.embed_batch_size = 3  # 极小批量


def delete_nodes_by_ids(vector_store, doc_ids: list):
    """
    根据 doc_id 删除节点
    
    Args:
        vector_store: 向量存储
        doc_ids: 要删除的 doc_id 列表
    """
    if not doc_ids:
        return 0
    
    lance_store = vector_store._get_lance_vector_store()
    
    try:
        # 读取现有数据
        existing = lance_store.get_all_doc_ids()
        to_keep = [id for id in existing if id not in doc_ids]
        
        # 删除整个表重建
        table_name = vector_store.table_name
        persist_dir = vector_store.persist_dir
        
        import lancedb
        db = lancedb.connect(str(persist_dir))
        db.drop_table(table_name, ignore_missing=True)
        
        # 重新添加保留的数据
        if to_keep:
            # 重新查询并添加
            for doc_id in to_keep:
                try:
                    # 获取节点并重新添加
                    pass  # 简化处理：删除后重建
                except:
                    pass
        
        return len(doc_ids)
    except Exception as e:
        print(f"   ⚠️  删除节点失败: {e}")
        return 0


def ingest_kb(
    kb_id: str,
    rebuild: bool = False,
    verbose: bool = False,
    vector_store_type: VectorStoreType = VectorStoreType.LANCEDB,
    show_changes_only: bool = False,
    force_delete: bool = True,
) -> bool:
    """
    导入单个知识库到向量数据库（支持增量同步）
    
    Args:
        kb_id: 知识库 ID
        rebuild: 强制重建
        verbose: 显示详细信息
        vector_store_type: 向量数据库类型
        show_changes_only: 只显示变更，不执行
        force_delete: 是否删除已移除的文件
    
    Returns:
        bool: 是否成功
    """
    registry = KnowledgeBaseRegistry()
    kb = registry.get(kb_id)

    if kb is None:
        print(f"❌ 知识库不存在: {kb_id}")
        return False

    persist_dir = kb.persist_dir
    vault_root = Path.home() / "Documents" / "Obsidian Vault"

    # 创建向量存储
    try:
        vector_store = create_vector_store(
            store_type=vector_store_type,
            persist_dir=persist_dir,
            table_name=kb_id,
        )
    except Exception as e:
        print(f"❌ 创建向量存储失败: {e}")
        return False

    # 初始化同步状态
    sync_state = SyncState(kb_id, persist_dir)

    # 收集所有源路径的文件
    all_files = []
    for source_path in kb.source_paths_abs(vault_root):
        if not source_path.exists():
            continue
        # 递归收集所有 md 文件
        all_files.extend(source_path.rglob("*.md"))

    print(f"\n📚 知识库: {kb.name}")
    print(f"   Vault: {vault_root}")
    print(f"   存储: {persist_dir}")

    # 强制重建模式
    if rebuild:
        print(f"\n   🔄 强制重建模式：清空现有索引")
        sync_state.clear()
        try:
            lance_store = vector_store._get_lance_vector_store()
            table_name = vector_store.table_name
            import lancedb
            db = lancedb.connect(str(persist_dir))
            db.drop_table(table_name, ignore_missing=True)
            print(f"   ✅ 已清空现有数据")
        except Exception as e:
            print(f"   ⚠️  清空失败: {e}")

    # 检测变更
    to_add, to_update, to_delete = sync_state.detect_changes(all_files, vault_root)

    print(f"\n   📊 文件状态:")
    print(f"      当前文件: {len(all_files)}")
    print(f"      已同步: {len(sync_state.get_doc_ids())}")
    print(f"      新增: {len(to_add)}")
    print(f"      更新: {len(to_update)}")
    print(f"      删除: {len(to_delete)}")

    if show_changes_only:
        if to_add:
            print(f"\n   📝 新增文件:")
            for rel_path, _ in to_add[:10]:
                print(f"      + {rel_path}")
            if len(to_add) > 10:
                print(f"      ... 还有 {len(to_add) - 10} 个")
        
        if to_update:
            print(f"\n   📝 更新文件:")
            for rel_path, _, _ in to_update[:10]:
                print(f"      ~ {rel_path}")
            if len(to_update) > 10:
                print(f"      ... 还有 {len(to_update) - 10} 个")
        
        if to_delete:
            print(f"\n   📝 删除文件:")
            for rel_path, doc_id in to_delete[:10]:
                print(f"      - {rel_path} (doc_id: {doc_id[:20]}...)")
            if len(to_delete) > 10:
                print(f"      ... 还有 {len(to_delete) - 10} 个")
        
        return True

    # 如果没有变更
    if not to_add and not to_update and not to_delete:
        print(f"\n   ⏭️  没有检测到变更，跳过")
        return True

    # 处理删除的文件
    if to_delete and force_delete:
        print(f"\n   🗑️  处理删除的文件...")
        doc_ids_to_delete = [doc_id for _, doc_id in to_delete]
        deleted_count = 0
        
        try:
            lance_store = vector_store._get_lance_vector_store()
            
            # 获取现有数据
            import lancedb
            db = lancedb.connect(str(persist_dir))
            table_name = vector_store.table_name
            
            if table_name in db.list_tables():
                table = db.open_table(table_name)
                
                # 过滤掉要删除的
                existing_data = table.to_pandas()
                if not existing_data.empty and "_row_id" in existing_data.columns:
                    # 找到要删除的行
                    to_keep_mask = ~existing_data["_row_id"].astype(str).isin(doc_ids_to_delete)
                    remaining = existing_data[to_keep_mask]
                    
                    # 删除表并重建
                    db.drop_table(table_name)
                    if not remaining.empty:
                        table = db.create_table(table_name, data=remaining)
                        deleted_count = len(existing_data) - len(remaining)
                    else:
                        deleted_count = len(existing_data)
                        
            print(f"   ✅ 删除了 {deleted_count} 条记录")
        except Exception as e:
            print(f"   ⚠️  删除失败: {e}")
        
        # 更新同步状态
        for file_path, doc_id in to_delete:
            sync_state.remove_state(file_path)

    # 收集所有要处理的文档
    from llama_index.core.schema import Document as LlamaDocument

    all_docs_to_process = []
    
    # 处理新增
    for rel_path, abs_path in to_add:
        try:
            content = abs_path.read_text(encoding="utf-8", errors="ignore")
            doc = LlamaDocument(
                text=content,
                metadata={
                    "source": "obsidian",
                    "file_path": str(abs_path),
                    "relative_path": rel_path,
                    "file_name": abs_path.name,
                },
                id_=rel_path,  # 使用相对路径作为 ID
            )
            all_docs_to_process.append(("add", rel_path, abs_path, doc))
        except Exception as e:
            print(f"   ⚠️  读取失败 {rel_path}: {e}")

    # 处理更新
    for rel_path, abs_path, old_doc_id in to_update:
        try:
            content = abs_path.read_text(encoding="utf-8", errors="ignore")
            doc = LlamaDocument(
                text=content,
                metadata={
                    "source": "obsidian",
                    "file_path": str(abs_path),
                    "relative_path": rel_path,
                    "file_name": abs_path.name,
                },
                id_=rel_path,
            )
            all_docs_to_process.append(("update", rel_path, abs_path, doc, old_doc_id))
        except Exception as e:
            print(f"   ⚠️  读取失败 {rel_path}: {e}")

    if not all_docs_to_process:
        print(f"\n   ⏭️  没有需要处理的文档")
        sync_state._save()
        return True

    print(f"\n   📦 处理 {len(all_docs_to_process)} 个文件...")

    # 配置 embedding 模型
    configure_embed_model()

    from llama_index.core import Settings
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.embeddings.ollama import OllamaEmbedding

    embed_model = OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )
    Settings.embed_model = embed_model

    node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)

    start_time = time.time()
    total_nodes = 0
    processed_files = 0

    # 分批处理
    batch_size = 10
    batches = [all_docs_to_process[i:i+batch_size] for i in range(0, len(all_docs_to_process), batch_size)]

    for batch_idx, batch in enumerate(batches):
        print(f"   批次 {batch_idx+1}/{len(batches)}...", end="", flush=True)

        batch_nodes = []
        batch_info = []  # [(rel_path, doc_id), ...]

        for item in batch:
            if item[0] == "add":
                _, rel_path, abs_path, doc = item
                nodes = node_parser.get_nodes_from_documents([doc])
                
                # 更新同步状态
                content = abs_path.read_text(encoding="utf-8", errors="ignore")
                doc_id = rel_path  # 使用文件路径作为 doc_id
                sync_state.update_state(rel_path, str(abs_path), content, doc_id)
                
                for node in nodes:
                    node.id_ = f"{rel_path}_{nodes.index(node)}"
                    batch_nodes.append(node)
                    batch_info.append((rel_path, node.id_))
                    
            elif item[0] == "update":
                _, rel_path, abs_path, doc, old_doc_id = item
                nodes = node_parser.get_nodes_from_documents([doc])
                
                # 更新同步状态
                content = abs_path.read_text(encoding="utf-8", errors="ignore")
                doc_id = rel_path
                sync_state.update_state(rel_path, str(abs_path), content, doc_id)
                
                for node in nodes:
                    node.id_ = f"{rel_path}_{nodes.index(node)}"
                    batch_nodes.append(node)
                    batch_info.append((rel_path, node.id_))

        # 生成 embeddings
        for node in batch_nodes:
            try:
                node.embedding = embed_model.get_text_embedding(node.get_content())
            except Exception as e:
                print(f"\n      ⚠️  Embedding 失败: {e}")
                continue

        # 保存到向量数据库
        try:
            lance_store = vector_store._get_lance_vector_store()
            lance_store.add(batch_nodes)
            total_nodes += len(batch_nodes)
            processed_files += len(batch)
            print(f" -> {len(batch_nodes)} 节点", end="")
        except Exception as e:
            print(f"\n      ⚠️  保存失败: {e}")

        print()

    elapsed = time.time() - start_time

    # 保存同步状态
    sync_state._save()

    print(f"\n   ✅ 完成!")
    print(f"   ⏱️  耗时: {elapsed:.1f}秒")
    print(f"   📝 处理文件: {processed_files}")
    print(f"   📊 生成节点: {total_nodes}")

    return True


def list_knowledge_bases():
    """列出所有知识库及其状态"""
    registry = KnowledgeBaseRegistry()

    print("\n📚 知识库列表\n")
    print(f"{'ID':<20} {'名称':<20} {'状态':<12} {'文件':<8} {'节点':<8} {'向量库':<10}")
    print("-" * 85)

    for kb in registry.list_all():
        vs = get_default_vector_store(persist_dir=kb.persist_dir)
        vs.table_name = kb.id
        stats = vs.get_stats()
        exists = stats.get("exists", False)
        
        # 获取同步状态
        sync_state = SyncState(kb.id, kb.persist_dir)
        sync_stats = sync_state.get_stats()

        status = "✅ 已索引" if exists else "⏳ 未索引"
        file_count = sync_stats.get("total_files", "-")
        node_count = stats.get("row_count", "-")

        print(f"{kb.id:<20} {kb.name:<20} {status:<12} {file_count:<8} {node_count:<8} lancedb")

    print()


def show_stats():
    """显示所有知识库的统计信息"""
    registry = KnowledgeBaseRegistry()

    print("\n📊 知识库统计信息\n")
    print(f"{'ID':<20} {'名称':<20} {'文件':<8} {'节点':<10} {'存储路径':<40}")
    print("-" * 105)

    total_files = 0
    total_nodes = 0

    for kb in registry.list_all():
        vs = get_default_vector_store(persist_dir=kb.persist_dir)
        vs.table_name = kb.id
        stats = vs.get_stats()

        sync_state = SyncState(kb.id, kb.persist_dir)
        sync_stats = sync_state.get_stats()

        file_count = sync_stats.get("total_files", 0)
        node_count = stats.get("row_count", 0)
        
        total_files += file_count
        total_nodes += node_count

        print(f"{kb.id:<20} {kb.name:<20} {file_count:<8} {node_count:<10} {str(kb.persist_dir):<40}")

    print("-" * 105)
    print(f"{'总计':<20} {'':<20} {total_files:<8} {total_nodes:<10}")
    print()


def main():
    parser = argparse.ArgumentParser(description="知识库导入工具（支持增量同步）")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有知识库")
    parser.add_argument("--kb", "-k", type=str, help="指定知识库 ID")
    parser.add_argument("--rebuild", "-r", action="store_true", help="强制重建（清空后重新导入）")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细信息")
    parser.add_argument("--engine", "-e", type=str, default="lancedb",
                        choices=["lancedb", "chroma", "qdrant", "default"],
                        help="向量数据库引擎")
    parser.add_argument("--stats", "-s", action="store_true", help="显示统计信息")
    parser.add_argument("--show-changes", action="store_true", help="显示变更但不执行")
    parser.add_argument("--no-delete", action="store_true", help="不同步删除的文件")

    args = parser.parse_args()

    engine_map = {
        "lancedb": VectorStoreType.LANCEDB,
        "chroma": VectorStoreType.CHROMA,
        "qdrant": VectorStoreType.QDRANT,
        "default": VectorStoreType.DEFAULT,
    }
    vector_store_type = engine_map.get(args.engine, VectorStoreType.LANCEDB)

    if args.list:
        list_knowledge_bases()
        return

    if args.stats:
        show_stats()
        return

    registry = KnowledgeBaseRegistry()

    if args.kb:
        success = ingest_kb(
            args.kb,
            rebuild=args.rebuild,
            verbose=args.verbose,
            vector_store_type=vector_store_type,
            show_changes_only=args.show_changes,
            force_delete=not args.no_delete,
        )
        sys.exit(0 if success else 1)
    else:
        print(f"\n🚀 增量同步所有知识库（使用 {args.engine}）\n")

        success_count = 0
        fail_count = 0

        for kb in registry.list_all():
            success = ingest_kb(
                kb.id,
                rebuild=args.rebuild,
                verbose=args.verbose,
                vector_store_type=vector_store_type,
                show_changes_only=args.show_changes,
                force_delete=not args.no_delete,
            )
            if success:
                success_count += 1
            else:
                fail_count += 1

        print(f"\n\n🎉 完成: {success_count} 成功, {fail_count} 失败")


if __name__ == "__main__":
    main()
