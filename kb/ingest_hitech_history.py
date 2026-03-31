#!/usr/bin/env python3
"""
高新技术企业历史项目库导入脚本

处理 2022-2024 年研发项目资料

用法:
    poetry run python -m kb.ingest_hitech_history              # 增量导入
    poetry run python -m kb.ingest_hitech_history --rebuild   # 强制重建
    poetry run python -m kb.ingest_hitech_history --status   # 查看状态
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Optional, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from llamaindex_study.vector_store import VectorStoreType, create_vector_store
from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


# 高新历史项目库配置
KB_NAME = "hitech_history"
KB_DISPLAY_NAME = "高新历史项目库"
TABLE_NAME = "hitech_history"
PERSIST_DIR = Path("/volumes/online/llamaindex/hitech_history")

# 数据源目录
DATA_SOURCES = [
    Path(
        "/Volumes/online/nutsync/2025年工作/【A】高新技术企业专项工作/AAA202501整改要求/2022年"
    ),
    Path(
        "/Volumes/online/nutsync/2025年工作/【A】高新技术企业专项工作/AAA202501整改要求/2023年"
    ),
    Path(
        "/Volumes/online/nutsync/2025年工作/【A】高新技术企业专项工作/AAA202501整改要求/2024年"
    ),
]

# 排除的文件类型（表格）
EXCLUDE_EXTENSIONS = {".xls", ".xlsx", ".DS_Store"}

# 支持的文件类型
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".md",
    ".pptx",
    ".xlsx",
    ".xls",
}


@dataclass
class ProgressState:
    """进度状态"""

    total_files: int = 0
    processed_files: int = 0
    total_nodes: int = 0
    processed_nodes: int = 0
    failed_files: List[str] = field(default_factory=list)
    started_at: Optional[float] = None
    last_file: Optional[str] = None

    def save(self, path: Path):
        """保存进度"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "ProgressState":
        """加载进度"""
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return cls(**json.load(f))
        return cls()


def configure_embed_model():
    """配置全局 Embedding 模型"""
    from llama_index.core import Settings as LlamaSettings
    from llama_index.embeddings.ollama import OllamaEmbedding
    from llamaindex_study.config import get_settings

    settings = get_settings()
    LlamaSettings.embed_model = OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )
    LlamaSettings.chunk_size = 512
    LlamaSettings.embed_batch_size = settings.embed_batch_size


def get_embed_model():
    """获取 Embedding 模型"""
    from llama_index.embeddings.ollama import OllamaEmbedding

    return OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )


def collect_files(directories: List[Path]) -> List[Path]:
    """收集所有支持的文件"""
    files = []
    image_exts = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".svg",
        ".webp",
        ".ico",
        ".tiff",
        ".tif",
        ".heic",
        ".avif",
    }
    supported_exts = {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".md",
        ".txt",
        ".html",
        ".htm",
    }

    for directory in directories:
        if not directory.exists():
            print(f"⚠️  目录不存在: {directory}")
            continue

        for root, _, filenames in os.walk(directory):
            for filename in filenames:
                file_path = Path(root) / filename
                ext = file_path.suffix.lower()

                # 排除表格文件
                if ext in EXCLUDE_EXTENSIONS:
                    continue

                # 排除图片文件
                if ext in image_exts:
                    continue

                # 排除隐藏文件
                if filename.startswith("."):
                    continue

                # 排除无扩展名或不在支持列表的文件
                if not ext or ext not in supported_exts:
                    continue

                files.append(file_path)

    return files


def process_file(
    file_path: Path, node_parser, embed_model, vector_store, batch_size: int = 50
) -> int:
    """处理单个文件"""
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core.schema import Document as LlamaDocument

    ext = file_path.suffix.lower()

    try:
        reader = SimpleDirectoryReader(
            input_files=[str(file_path)],
            filename_as_id=True,
        )
        docs = reader.load_data()

        if not docs:
            return 0

        # 获取相对路径作为来源标识
        rel_path = file_path.name

        all_nodes = []
        for doc in docs:
            llama_doc = LlamaDocument(
                text=doc.text,
                metadata={
                    "source": "hitech_history",
                    "file_path": str(file_path),
                    "file_name": file_path.name,
                    "file_ext": ext,
                    "file_size": file_path.stat().st_size if file_path.exists() else 0,
                },
                id_=f"hitech_{file_path.stem}_{id(doc)}",
            )
            nodes = node_parser.get_nodes_from_documents([llama_doc])
            all_nodes.extend(nodes)

        # 批量保存
        while len(all_nodes) >= batch_size:
            batch = all_nodes[:batch_size]
            all_nodes = all_nodes[batch_size:]
            save_batch(vector_store, batch, embed_model)

        # 保存剩余
        if all_nodes:
            save_batch(vector_store, all_nodes, embed_model)

        return len(docs)

    except Exception as e:
        print(f"   ⚠️  处理失败: {file_path.name} - {e}")
        return 0


def save_batch(vector_store, nodes, embed_model):
    """保存一批节点"""
    if not nodes:
        return

    try:
        # 生成 embeddings
        for node in nodes:
            try:
                node.embedding = embed_model.get_text_embedding(node.get_content())
            except Exception as e:
                print(f"\n   ⚠️  Embedding 失败: {e}")
                continue

        # 保存到 LanceDB
        lance_store = vector_store._get_lance_vector_store()
        lance_store.add(nodes)

    except Exception as e:
        print(f"\n   ⚠️  保存失败: {e}")


def ingest_hitech_history(
    persist_dir: Path,
    data_sources: List[Path],
    rebuild: bool = False,
    batch_size: int = 50,
) -> bool:
    """
    导入高新技术企业历史项目资料
    """
    from llamaindex_study.node_parser import get_node_parser

    print(f"\n{'=' * 60}")
    print(f"🏢 {KB_DISPLAY_NAME}")
    print(f"{'=' * 60}")

    progress_file = persist_dir / f".{TABLE_NAME}_progress.json"

    # 创建向量存储
    vector_store = create_vector_store(
        store_type=VectorStoreType.LANCEDB,
        persist_dir=persist_dir,
        table_name=TABLE_NAME,
    )

    # 加载进度
    progress = ProgressState.load(progress_file)

    if rebuild:
        print(f"🔄 重建模式：清空现有数据")
        try:
            vector_store.delete_table()
        except Exception:
            pass
        progress = ProgressState()

    # 收集文件
    print(f"\n📂 收集文件...")
    all_files = collect_files(data_sources)
    print(f"   找到 {len(all_files)} 个文件")

    if not all_files:
        print(f"❌ 没有找到文件")
        return False

    progress.total_files = len(all_files)
    progress.started_at = time.time()

    # 配置 embedding 模型
    configure_embed_model()
    embed_model = get_embed_model()
    node_parser = get_node_parser(chunk_size=512, chunk_overlap=50)

    # 已处理文件集合
    processed_set = (
        set(progress.processed_files)
        if isinstance(progress.processed_files, list)
        else set()
    )

    print(f"\n🚀 开始导入 (每 {batch_size} 节点保存一次)")

    if not rebuild and progress.processed_files:
        print(f"   📊 断点续传: 已处理 {progress.processed_files} 个文件")

    total_nodes = 0

    for i, file_path in enumerate(all_files):
        if str(file_path) in processed_set:
            continue

        elapsed = time.time() - progress.started_at if progress.started_at else 0

        if i % 10 == 0:
            print(
                f"\n   进度: {i + 1}/{len(all_files)} ({100 * (i + 1) // len(all_files)}%)"
            )
            print(f"   节点: {total_nodes}, 耗时: {elapsed:.0f}s")

        # 显示文件信息
        file_size = file_path.stat().st_size / 1024
        ext = file_path.suffix.lower()
        print(f"   📄 {file_path.name[:40]}... ({file_size:.0f}KB)")

        nodes_count = process_file(
            file_path, node_parser, embed_model, vector_store, batch_size
        )

        total_nodes += nodes_count
        progress.processed_files = i + 1
        progress.total_nodes = total_nodes
        progress.last_file = str(file_path)
        progress.save(progress_file)

    # 统计
    stats = vector_store.get_stats()

    elapsed = time.time() - progress.started_at if progress.started_at else 0

    print(f"\n{'=' * 60}")
    print(f"✅ 完成!")
    print(f"   ⏱️  耗时: {elapsed:.1f}秒")
    print(f"   📄 文件: {progress.processed_files}/{progress.total_files}")
    print(f"   📊 节点: {total_nodes}")
    print(f"   💾 向量: {stats.get('row_count', 'N/A')}")

    if progress.failed_files:
        print(f"   ⚠️  失败: {len(progress.failed_files)} 个")

    # 删除进度文件（完成）
    progress_file.unlink(missing_ok=True)

    return True


def show_status():
    """显示导入状态"""
    progress_file = PERSIST_DIR / f".{TABLE_NAME}_progress.json"

    vector_store = create_vector_store(
        store_type=VectorStoreType.LANCEDB,
        persist_dir=PERSIST_DIR,
        table_name=TABLE_NAME,
    )

    print(f"\n📊 {KB_DISPLAY_NAME} 导入状态\n")

    if progress_file.exists():
        progress = ProgressState.load(progress_file)
        elapsed = time.time() - progress.started_at if progress.started_at else 0

        print(f"   文件进度: {progress.processed_files}/{progress.total_files}")
        print(f"   节点: {progress.total_nodes}")
        print(f"   耗时: {elapsed:.0f}秒")

        if progress.last_file:
            print(f"   上次位置: {Path(progress.last_file).name}")
    else:
        print(f"   无进行中的任务")

    stats = vector_store.get_stats()
    print(f"\n   💾 向量数据库: {stats.get('row_count', 0)} 条记录")
    print(f"   📁 存储: {PERSIST_DIR}")


def main():
    parser = argparse.ArgumentParser(description=f"{KB_DISPLAY_NAME}导入工具")
    parser.add_argument("--status", "-s", action="store_true", help="查看状态")
    parser.add_argument("--rebuild", "-r", action="store_true", help="强制重建")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    success = ingest_hitech_history(
        persist_dir=PERSIST_DIR,
        data_sources=DATA_SOURCES,
        rebuild=args.rebuild,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
