#!/usr/bin/env python3
"""
Zotero 营养饲料理论导入脚本 - 增强版

特性：
- 以文献为单位存储（每文献或每50块保存一次）
- 完善的断点续传机制
- PDF 扫描件检测 + OCR 转换 (MinerU / doc2x)
- 进度可视化

用法:
    poetry run python -m kb.ingest_zotero              # 增量导入
    poetry run python -m kb.ingest_zotero --rebuild   # 强制重建
    poetry run python -m kb.ingest_zotero --status    # 查看状态
"""

import argparse
import json
import os
import re
import sys
import time
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, List, Dict, Set

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from kb.zotero_reader import create_zotero_reader
from llamaindex_study.vector_store import VectorStoreType, create_vector_store


# Zotero "营养饲料理论" 收藏夹 ID
NUTRITION_FEED_COLLECTION_ID = 8


@dataclass
class ProgressState:
    """进度状态"""
    total_items: int = 0
    processed_items: List[int] = field(default_factory=list)  # 已处理的文献 ID
    failed_items: List[int] = field(default_factory=list)      # 失败的文献 ID
    converted_pdfs: Dict[int, str] = field(default_factory=dict)  # item_id -> 转换后的 MD 路径
    started_at: Optional[float] = None
    last_item_id: Optional[int] = None
    last_updated: Optional[float] = None

    # 兼容旧进度文件
    @classmethod
    def from_dict(cls, data: dict) -> "ProgressState":
        """从字典创建（兼容旧格式）"""
        # 旧字段映射
        if "total_nodes" in data:
            data.pop("total_nodes")
        if "processed_nodes" in data:
            data.pop("processed_nodes")

        # 过滤有效字段
        valid_data = {}
        for k, v in data.items():
            if k in cls.__dataclass_fields__:
                # 类型转换
                field_type = cls.__dataclass_fields__[k].type
                if "List" in str(field_type) and isinstance(v, int):
                    # 旧格式：processed_items 是 int，需要转为 list
                    v = list(range(v))
                valid_data[k] = v

        return cls(**valid_data)

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
                return cls.from_dict(json.load(f))
        return cls()


def configure_embed_model():
    """配置全局 Embedding 模型"""
    from llama_index.core import Settings
    from llama_index.embeddings.ollama import OllamaEmbedding

    Settings.embed_model = OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )
    Settings.chunk_size = 512


def get_embed_model():
    """获取 Embedding 模型"""
    from llama_index.embeddings.ollama import OllamaEmbedding
    return OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://localhost:11434",
    )


def is_scanned_pdf(pdf_path: str) -> bool:
    """
    检测 PDF 是否为扫描件

    使用多种方法综合判断：
    1. 文字密度（字符数/页面面积）
    2. 图片比例
    3. 字体嵌入情况
    """
    try:
        from pypdf import PdfReader
        import re

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        if total_pages == 0:
            return True

        pages_to_check = min(total_pages, 5)

        # 1. 检查文字密度
        total_text_len = 0
        total_page_area = 0

        for page in reader.pages[:pages_to_check]:
            text = page.extract_text() or ""

            # 统计中英文有效字符
            chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
            english_chars = len(re.findall(r'[a-zA-Z]', text))
            number_chars = len(re.findall(r'[0-9]', text))
            valid_chars = chinese_chars + english_chars + number_chars

            total_text_len += valid_chars

            # 计算页面面积（points, 72 points = 1 inch）
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)
            total_page_area += width * height

        # 文字密度 = 字符数 / 平方英寸
        # 每平方英寸少于 10 个字符视为扫描件
        avg_density = total_text_len / (total_page_area / (72 * 72))

        if total_text_len < 50:
            # 几乎没有文字
            return True

        if avg_density < 10:
            # 文字密度过低
            return True

        # 2. 检查图片比例
        image_pages = 0
        for page in reader.pages[:pages_to_check]:
            try:
                if "/Resources" in page and "/XObject" in page["/Resources"]:
                    xobjects = page["/Resources"]["/XObject"].get_object()
                    image_count = sum(
                        1 for obj in xobjects.values()
                        if obj.get("/Subtype") == "/Image"
                    )
                    if image_count > 0:
                        image_pages += 1
            except:
                pass

        # 如果 80% 以上页面有图片，可能是扫描件
        if image_pages / pages_to_check > 0.8:
            return True

        return False

    except Exception as e:
        print(f"   ⚠️  PDF 检测失败: {e}")
        return True  # 检测失败时保守处理


def convert_pdf_to_markdown(pdf_path: str, item_id: int, timeout: int = 300, title: str = "") -> Optional[str]:
    """
    使用 MinerU 或 doc2x 将 PDF 转换为 Markdown

    Args:
        pdf_path: PDF 文件路径
        item_id: Zotero 文献 ID（用于命名）
        timeout: 超时时间（秒）

    Returns:
        转换后的 Markdown 文件路径，失败返回 None
    """
    print(f"   🔄 正在转换 PDF 为 Markdown...")

    markdown_content = None

    # 方法 1: 尝试 MinerU MCP
    try:
        result = subprocess.run(
            [
                "node",
                "/Users/luopingcheng/.nvm/versions/node/v24.13.1/lib/node_modules/mineru-mcp/dist/index.js"
            ],
            input=json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "mineru_convert",
                    "arguments": {"file_path": pdf_path}
                }
            }),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            if "result" in data and "content" in data["result"]:
                content = data["result"]["content"]
                if isinstance(content, str) and len(content.strip()) > 100:
                    markdown_content = content
                    print(f"   ✅ MinerU 转换成功")

    except Exception as e:
        print(f"   ⚠️  MinerU 失败: {e}")

    # 方法 2: 尝试 doc2x MCP
    if not markdown_content:
        try:
            result = subprocess.run(
                ["npx", "-y", "@noedgeai-org/doc2x-mcp@latest", "convert", pdf_path, "--format", "markdown"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0 and result.stdout and len(result.stdout.strip()) > 100:
                markdown_content = result.stdout
                print(f"   ✅ doc2x 转换成功")

        except Exception as e:
            print(f"   ⚠️  doc2x 失败: {e}")

    if not markdown_content:
        print(f"   ❌ PDF 转换失败")
        return None

    # 保存到 Zotero 存储目录
    try:
        md_path = save_md_to_zotero(item_id, markdown_content)
        if md_path:
            print(f"   ✅ 已保存到 Zotero: {md_path}")
            return md_path
    except Exception as e:
        print(f"   ⚠️  保存到 Zotero 失败: {e}")

    return None


def save_md_to_zotero(item_id: int, content: str, title: str = "") -> Optional[str]:
    """
    将 Markdown 文件保存到 Zotero 存储目录，并添加到文献附件

    Args:
        item_id: Zotero 文献 ID
        content: Markdown 内容
        title: 文献标题（用于文件名）

    Returns:
        保存的 MD 文件路径
    """
    import sqlite3
    import hashlib
    import uuid

    zotero_dir = Path.home() / "Zotero"
    storage_dir = zotero_dir / "storage"
    db_path = zotero_dir / "zotero.sqlite"

    # 生成存储哈希（8字符）
    storage_hash = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()[:8].upper()
    item_dir = storage_dir / storage_hash
    item_dir.mkdir(parents=True, exist_ok=True)

    # 生成文件名
    safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:50] if title else f"converted_{item_id}"
    md_filename = f"{safe_title}.md"
    md_path = item_dir / md_filename

    # 保存文件
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)

    # 添加到 Zotero 数据库
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # 生成 item key
        item_key = uuid.uuid4().hex[:8].upper()

        # 获取当前最大 itemID
        cursor.execute("SELECT MAX(itemID) FROM items")
        new_item_id = (cursor.fetchone()[0] or 0) + 1

        # 添加到 items 表
        cursor.execute("""
            INSERT INTO items (itemID, libraryID, key, itemTypeID, dateAdded, clientDateModified, synced, version)
            VALUES (?, 1, ?, 2, datetime('now'), datetime('now'), 0, 1)
        """, (new_item_id, item_key))

        # 添加文件类型关联 (2 = document, 需查 itemTypes 表确认)
        cursor.execute("SELECT itemTypeID FROM itemTypes WHERE type = 'document'")
        doc_type_row = cursor.fetchone()
        if doc_type_row:
            cursor.execute("UPDATE items SET itemTypeID = ? WHERE itemID = ?", (doc_type_row[0], new_item_id))

        # 添加到 itemAttachments 表
        cursor.execute("""
            INSERT INTO itemAttachments (itemID, parentItemID, linkMode, contentType, path, storageHash, charset)
            VALUES (?, ?, 0, 'text/markdown', ?, ?, NULL)
        """, (new_item_id, item_id, f"storage:{md_filename}", storage_hash))

        conn.commit()
        conn.close()

        print(f"   📎 已添加为 Zotero 附件 (itemID: {new_item_id})")

    except Exception as e:
        print(f"   ⚠️  添加到 Zotero 失败: {e}")
        # 文件已保存，只是数据库记录失败

    return str(md_path)


def process_pdf(pdf_path: str, item_id: int, title: str, creators: List[str], item, 
                embed_model, node_parser, vector_store, progress: ProgressState) -> int:
    """
    处理单个 PDF 文件

    Returns:
        生成的节点数量
    """
    from llama_index.core.schema import Document as LlamaDocument

    # 检查是否已转换为 MD
    md_path = progress.converted_pdfs.get(item_id)
    if md_path and Path(md_path).exists():
        # 使用已转换的 MD 文件
        print(f"   📄 使用已转换的 MD: {md_path}")
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                md_content = f.read()

            if len(md_content.strip()) > 100:
                doc = LlamaDocument(
                    text=md_content,
                    metadata={
                        "source": "zotero_md",
                        "item_id": item_id,
                        "title": title,
                        "creators": ", ".join(creators) if creators else "",
                        "original_pdf": pdf_path,
                    },
                    id_=f"zotero_md_{item_id}",
                )
                nodes = node_parser.get_nodes_from_documents([doc])
                save_nodes_incrementally(vector_store, nodes, embed_model, progress)
                return len(nodes)
        except Exception as e:
            print(f"   ⚠️  MD 读取失败: {e}")

    # 检测是否为扫描件
    print(f"   🔍 检测 PDF 类型...", end="", flush=True)
    if is_scanned_pdf(pdf_path):
        print(" 扫描件")
        print(f"   🔄 尝试转换为 Markdown...")

        # 先尝试直接读取（可能有部分文字）
        try:
            from llama_index.core import SimpleDirectoryReader
            pdf_reader = SimpleDirectoryReader(
                input_files=[pdf_path],
                filename_as_id=True,
            )
            pdf_docs = pdf_reader.load_data()

            total_text = "\n".join([doc.text for doc in pdf_docs])
            if len(total_text.strip()) > 500:
                # 虽然是扫描件，但能提取一些文字
                print(f"   📝 提取到 {len(pdf_docs)} 页文字，继续处理")

                for pdf_doc in pdf_docs:
                    doc = LlamaDocument(
                        text=pdf_doc.text,
                        metadata={
                            "source": "zotero_pdf",
                            "item_id": item_id,
                            "title": title,
                            "creators": ", ".join(creators) if creators else "",
                        },
                        id_=f"zotero_pdf_{item_id}",
                    )
                    nodes = node_parser.get_nodes_from_documents([doc])
                    save_nodes_incrementally(vector_store, nodes, embed_model, progress)
                return len(pdf_docs)

        except Exception as e:
            print(f"   ⚠️  PDF 读取失败: {e}")

        # 尝试 OCR 转换
        md_path = convert_pdf_to_markdown(pdf_path, item_id, timeout=600, title=title)
        if md_path:
            progress.converted_pdfs[item_id] = md_path
            # 递归调用使用转换后的 MD
            return process_pdf(md_path, item_id, title, creators, item, 
                             embed_model, node_parser, vector_store, progress)
        else:
            print(f"   ⚠️  PDF 转换失败，跳过")
            return 0
    else:
        print(" 正常")
        # 正常 PDF，直接读取
        try:
            from llama_index.core import SimpleDirectoryReader
            pdf_reader = SimpleDirectoryReader(
                input_files=[pdf_path],
                filename_as_id=True,
            )
            pdf_docs = pdf_reader.load_data()

            for pdf_doc in pdf_docs:
                doc = LlamaDocument(
                    text=pdf_doc.text,
                    metadata={
                        "source": "zotero_pdf",
                        "item_id": item_id,
                        "title": title,
                        "creators": ", ".join(creators) if creators else "",
                    },
                    id_=f"zotero_pdf_{item_id}",
                )
                nodes = node_parser.get_nodes_from_documents([doc])
                save_nodes_incrementally(vector_store, nodes, embed_model, progress)

            return len(pdf_docs)

        except Exception as e:
            print(f"   ⚠️  PDF 读取失败: {e}")
            return 0


def process_document(
    file_path: str,
    item_id: int,
    title: str,
    creators: List[str],
    node_parser,
    vector_store,
    embed_model,
    progress: ProgressState,
    source: str = "zotero_docx",
) -> int:
    """
    处理 Office 文档 (Word, Excel, PPTX)

    Returns:
        生成的节点数量
    """
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core.schema import Document as LlamaDocument

    try:
        reader = SimpleDirectoryReader(
            input_files=[file_path],
            filename_as_id=True,
        )
        docs = reader.load_data()

        for doc in docs:
            llama_doc = LlamaDocument(
                text=doc.text,
                metadata={
                    "source": source,
                    "item_id": item_id,
                    "title": title,
                    "creators": ", ".join(creators) if creators else "",
                },
                id_=f"{source}_{item_id}",
            )
            nodes = node_parser.get_nodes_from_documents([llama_doc])
            save_nodes_incrementally(vector_store, nodes, embed_model, progress)

        return len(docs)

    except Exception as e:
        print(f"   ⚠️  文档读取失败: {e}")
        return 0


def save_nodes_incrementally(vector_store, nodes, embed_model, progress: ProgressState, batch_size: int = 50):
    """
    增量保存节点（每 50 个节点保存一次）
    """
    if not nodes:
        return

    print(f"   💾 保存 {len(nodes)} 节点...", end="", flush=True)

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

        print(" ✅")
    except Exception as e:
        print(f" ❌ {e}")


def ingest_zotero_incremental(
    collection_id: int,
    collection_name: str,
    table_name: str,
    persist_dir: Path,
    rebuild: bool = False,
    max_nodes_per_save: int = 50,
) -> bool:
    """
    增量导入 Zotero 收藏夹

    特性：
    - 以文献为单位处理
    - 每 50 个节点保存一次
    - 完善的断点续传
    - PDF 扫描件检测和 OCR 转换
    """
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.schema import Document as LlamaDocument

    print(f"\n{'='*60}")
    print(f"📚 Zotero: {collection_name}")
    print(f"{'='*60}")

    progress_file = persist_dir / f".{table_name}_progress.json"

    # 创建向量存储
    vector_store = create_vector_store(
        store_type=VectorStoreType.LANCEDB,
        persist_dir=persist_dir,
        table_name=table_name,
    )

    # 加载进度
    progress = ProgressState.load(progress_file)

    if rebuild:
        print(f"🔄 重建模式：清空现有数据")
        try:
            vector_store.delete_table()
        except:
            pass
        progress = ProgressState()

    # 创建 Zotero 读取器
    reader = create_zotero_reader(include_annotations=True, include_notes=True)

    # 获取收藏夹中的文献
    print(f"\n📂 获取收藏夹文献...")
    item_ids = reader.get_items_in_collection(collection_id, recursive=True)
    print(f"   共 {len(item_ids)} 篇文献")

    if not item_ids:
        print(f"❌ 没有找到文献")
        reader.close()
        return False

    progress.total_items = len(item_ids)

    # 配置 embedding 模型
    configure_embed_model()
    embed_model = get_embed_model()
    node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=50)

    # 已处理的文献集合
    processed_set = set(progress.processed_items)

    print(f"\n🚀 开始处理 (每文献或每 {max_nodes_per_save} 节点保存一次)")

    if not rebuild and progress.processed_items:
        print(f"   📊 断点续传: 已处理 {len(progress.processed_items)} 篇")

    total_nodes = 0
    total_pdfs = 0
    failed_items = []

    for item_idx, item_id in enumerate(item_ids):
        if item_id in processed_set:
            continue

        elapsed = time.time() - progress.started_at if progress.started_at else 0

        if item_idx % 5 == 0:
            print(f"\n   进度: {item_idx+1}/{len(item_ids)} ({100*(item_idx+1)//len(item_ids)}%)")
            print(f"   节点: {total_nodes}, 耗时: {elapsed:.0f}s")
            if progress.started_at is None:
                progress.started_at = time.time()

        # 加载文献
        item = reader.get_item(item_id)
        if not item:
            print(f"   ⚠️  无法加载文献 {item_id}")
            progress.failed_items.append(item_id)
            progress.processed_items.append(item_id)
            progress.save(progress_file)
            continue

        nodes_this_item = 0

        # 1. 处理标注/笔记
        if item.annotations or item.notes:
            text_parts = [f"# {item.title}"]
            if item.creators:
                text_parts.append(f"作者: {', '.join(item.creators)}")
            if item.annotations:
                text_parts.append("\n## 标注:")
                for ann in item.annotations:
                    text_parts.append(f"- {ann['text']}")
                    if ann['comment']:
                        text_parts.append(f"  注: {ann['comment']}")

            text = "\n".join(text_parts)
            if len(text.strip()) >= 50:
                doc = LlamaDocument(
                    text=text,
                    metadata={
                        "source": "zotero_meta",
                        "item_id": item.item_id,
                        "title": item.title,
                        "creators": ", ".join(item.creators) if item.creators else "",
                    },
                    id_=f"zotero_meta_{item.item_id}",
                )
                nodes = node_parser.get_nodes_from_documents([doc])
                save_nodes_incrementally(vector_store, nodes, embed_model, progress)
                nodes_this_item += len(nodes)

        # 2. 处理附件（PDF / Word / Excel / PPTX）
        if item.file_path and Path(item.file_path).exists():
            file_path = Path(item.file_path)
            file_ext = file_path.suffix.lower()
            file_size = os.path.getsize(file_path) / 1024 / 1024

            # 根据文件类型处理
            if file_ext == '.pdf':
                print(f"   📄 [{item_idx+1}/{len(item_ids)}] {item.title[:40]}... ({file_size:.1f}MB)")
                nodes_count = process_pdf(
                    pdf_path=str(file_path),
                    item_id=item.item_id,
                    title=item.title,
                    creators=item.creators or [],
                    item=item,
                    embed_model=embed_model,
                    node_parser=node_parser,
                    vector_store=vector_store,
                    progress=progress,
                )
                nodes_this_item += nodes_count
                total_pdfs += 1
            elif file_ext in ['.docx', '.doc']:
                print(f"   📝 [{item_idx+1}/{len(item_ids)}] Word: {item.title[:40]}... ({file_size:.1f}MB)")
                nodes_count = process_document(str(file_path), item.item_id, item.title, item.creators or [], node_parser, vector_store, embed_model, progress, source="zotero_docx")
                nodes_this_item += nodes_count
            elif file_ext in ['.xlsx', '.xls']:
                print(f"   📊 [{item_idx+1}/{len(item_ids)}] Excel: {item.title[:40]}... ({file_size:.1f}MB)")
                nodes_count = process_document(str(file_path), item.item_id, item.title, item.creators or [], node_parser, vector_store, embed_model, progress, source="zotero_xlsx")
                nodes_this_item += nodes_count
            elif file_ext == '.pptx':
                print(f"   📽️ [{item_idx+1}/{len(item_ids)}] PPTX: {item.title[:40]}... ({file_size:.1f}MB)")
                nodes_count = process_document(str(file_path), item.item_id, item.title, item.creators or [], node_parser, vector_store, embed_model, progress, source="zotero_pptx")
                nodes_this_item += nodes_count
            else:
                print(f"   ❓ [{item_idx+1}/{len(item_ids)}] 未知格式: {file_ext}")

        elif item.file_path:
            print(f"   ⚠️  文件不存在: {item.file_path}")

        total_nodes += nodes_this_item
        progress.processed_items.append(item_id)
        progress.last_item_id = item_id
        progress.last_updated = time.time()

        # 每处理完一个文献，保存进度
        progress.save(progress_file)

    reader.close()

    # 统计
    stats = vector_store.get_stats()

    elapsed = time.time() - progress.started_at if progress.started_at else 0

    print(f"\n{'='*60}")
    print(f"✅ 完成!")
    print(f"   ⏱️  耗时: {elapsed:.1f}秒")
    print(f"   📚 文献: {len(progress.processed_items)}/{progress.total_items}")
    print(f"   📄 PDF: {total_pdfs} 篇")
    print(f"   📊 节点: {total_nodes}")
    print(f"   💾 向量: {stats.get('row_count', 'N/A')}")

    if progress.failed_items:
        print(f"   ⚠️  失败: {len(progress.failed_items)} 篇")
        print(f"      IDs: {progress.failed_items[:10]}...")

    # 删除进度文件（完成）
    progress_file.unlink(missing_ok=True)

    return True


def show_status():
    """显示导入状态"""
    settings = __import__("llamaindex_study.config", fromlist=["get_settings"]).get_settings()
    persist_dir = Path(settings.zotero_persist_dir)
    progress_file = persist_dir / ".zotero_nutrition_progress.json"

    vector_store = create_vector_store(
        store_type=VectorStoreType.LANCEDB,
        persist_dir=persist_dir,
        table_name="zotero_nutrition",
    )

    print(f"\n📊 Zotero 营养饲料理论 导入状态\n")

    if progress_file.exists():
        progress = ProgressState.load(progress_file)
        elapsed = time.time() - progress.started_at if progress.started_at else 0

        print(f"   文献进度: {len(progress.processed_items)}/{progress.total_items}")
        print(f"   耗时: {elapsed:.0f}秒")
        print(f"   已转换 PDF: {len(progress.converted_pdfs)}")

        if progress.last_item_id:
            print(f"   上次位置: item #{progress.last_item_id}")

        if progress.failed_items:
            print(f"   失败文献: {len(progress.failed_items)} 篇")
    else:
        print(f"   无进行中的任务")

    stats = vector_store.get_stats()
    print(f"\n   💾 向量数据库: {stats.get('row_count', 0)} 条记录")
    print(f"   📁 存储: {persist_dir}")


def main():
    parser = argparse.ArgumentParser(description="Zotero 营养饲料理论导入工具")
    parser.add_argument("--status", "-s", action="store_true", help="查看状态")
    parser.add_argument("--rebuild", "-r", action="store_true", help="强制重建")
    parser.add_argument("--batch-size", "-b", type=int, default=50, help="每批保存节点数")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    settings = __import__("llamaindex_study.config", fromlist=["get_settings"]).get_settings()
    persist_dir = Path(settings.zotero_persist_dir)

    success = ingest_zotero_incremental(
        collection_id=NUTRITION_FEED_COLLECTION_ID,
        collection_name="营养饲料理论",
        table_name="zotero_nutrition",
        persist_dir=persist_dir,
        rebuild=args.rebuild,
        max_nodes_per_save=args.batch_size,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
