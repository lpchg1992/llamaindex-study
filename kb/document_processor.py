"""
通用文档处理器

提供统一的文档处理能力：
- PDF 扫描件检测
- PDF 转 Markdown (MinerU / doc2x)
- Office 文档处理 (Word, Excel, PPTX)
- 批量处理和增量保存
- 断点续传

供所有导入脚本使用
"""

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, List, Callable

from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document as LlamaDocument


@dataclass
class DocumentProcessorConfig:
    """文档处理器配置"""
    chunk_size: int = 512
    chunk_overlap: int = 50
    batch_size: int = 50  # 每 N 个节点保存一次
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    pdf_scan_threshold: float = 10.0  # 文字密度阈值 (chars/sq inch)
    pdf_image_ratio_threshold: float = 0.8  # 图片比例阈值
    pdf_convert_timeout: int = 600  # PDF 转换超时 (秒)


@dataclass
class ProcessingProgress:
    """处理进度"""
    total_items: int = 0
    processed_items: List[str] = field(default_factory=list)  # 文件路径或 ID
    failed_items: List[str] = field(default_factory=list)
    converted_files: dict = field(default_factory=dict)  # 原路径 -> 转换后路径
    started_at: Optional[float] = None
    last_item: Optional[str] = None
    total_nodes: int = 0

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "ProcessingProgress":
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return cls(**json.load(f))
        return cls()


class DocumentProcessor:
    """
    通用文档处理器

    提供统一的文档处理接口，支持：
    - PDF (含扫描件检测和 OCR)
    - Word (docx, doc)
    - Excel (xlsx, xls)
    - PPTX
    - Markdown
    - 纯文本
    """

    def __init__(
        self,
        config: Optional[DocumentProcessorConfig] = None,
        embed_model=None,
        node_parser=None,
    ):
        self.config = config or DocumentProcessorConfig()
        self.embed_model = embed_model
        self.node_parser = node_parser or SentenceSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )

    def set_embed_model(self, embed_model):
        """设置 embedding 模型"""
        self.embed_model = embed_model

    def is_scanned_pdf(self, pdf_path: str) -> bool:
        """
        检测 PDF 是否为扫描件

        方法：
        1. 文字密度（字符数/页面面积）
        2. 图片比例
        """
        try:
            from pypdf import PdfReader

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
                chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
                english_chars = len(re.findall(r'[a-zA-Z]', text))
                number_chars = len(re.findall(r'[0-9]', text))
                valid_chars = chinese_chars + english_chars + number_chars
                total_text_len += valid_chars

                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                total_page_area += width * height

            avg_density = total_text_len / (total_page_area / (72 * 72))

            if total_text_len < 50:
                return True

            if avg_density < self.config.pdf_scan_threshold:
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

            if image_pages / pages_to_check > self.config.pdf_image_ratio_threshold:
                return True

            return False

        except Exception as e:
            print(f"   ⚠️  PDF 检测失败: {e}")
            return True  # 保守处理

    def convert_pdf_to_markdown(self, pdf_path: str, timeout: int = None) -> Optional[str]:
        """
        将 PDF 转换为 Markdown

        方法：
        1. MinerU MCP
        2. doc2x MCP

        Returns:
            转换后的 Markdown 内容，失败返回 None
        """
        timeout = timeout or self.config.pdf_convert_timeout
        print(f"   🔄 正在转换 PDF 为 Markdown...")

        markdown_content = None

        # 方法 1: MinerU MCP
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

        # 方法 2: doc2x MCP
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

        return markdown_content

    def process_pdf(self, pdf_path: str, metadata: dict = None) -> List[LlamaDocument]:
        """
        处理 PDF 文件

        Args:
            pdf_path: PDF 文件路径
            metadata: 额外的元数据

        Returns:
            LlamaDocument 列表
        """
        docs = []
        ext = Path(pdf_path).suffix.lower()

        # 检查是否需要转换
        is_scanned = self.is_scanned_pdf(pdf_path)

        if is_scanned:
            print(f"   🔍 检测为扫描件，尝试 OCR 转换...")
            md_content = self.convert_pdf_to_markdown(pdf_path)
            if md_content:
                doc = LlamaDocument(
                    text=md_content,
                    metadata={
                        "source": "pdf_scanned",
                        "file_path": pdf_path,
                        "converted": True,
                        **(metadata or {}),
                    },
                )
                docs.append(doc)
            else:
                # 尝试直接读取（可能有部分文字）
                try:
                    reader = SimpleDirectoryReader(input_files=[pdf_path])
                    raw_docs = reader.load_data()
                    for doc in raw_docs:
                        if len(doc.text.strip()) > 500:
                            doc.metadata["source"] = "pdf_partial"
                            doc.metadata.update(metadata or {})
                            docs.append(doc)
                except:
                    pass
        else:
            # 正常 PDF
            try:
                reader = SimpleDirectoryReader(input_files=[pdf_path])
                raw_docs = reader.load_data()
                for doc in raw_docs:
                    doc.metadata["source"] = "pdf"
                    doc.metadata["file_path"] = pdf_path
                    doc.metadata.update(metadata or {})
                    docs.append(doc)
            except Exception as e:
                print(f"   ⚠️  PDF 读取失败: {e}")

        return docs

    def process_document(self, file_path: str, metadata: dict = None) -> List[LlamaDocument]:
        """
        处理通用文档（Word, Excel, PPTX, Markdown, TXT）

        Args:
            file_path: 文件路径
            metadata: 额外的元数据

        Returns:
            LlamaDocument 列表
        """
        docs = []
        path = Path(file_path)
        ext = path.suffix.lower()

        try:
            reader = SimpleDirectoryReader(input_files=[str(path)])
            raw_docs = reader.load_data()

            source_map = {
                '.docx': 'word',
                '.doc': 'word',
                '.xlsx': 'excel',
                '.xls': 'excel',
                '.pptx': 'pptx',
                '.md': 'markdown',
                '.txt': 'text',
                '.html': 'html',
            }

            source = source_map.get(ext, 'document')

            for doc in raw_docs:
                doc.metadata["source"] = source
                doc.metadata["file_path"] = str(path)
                doc.metadata.update(metadata or {})
                docs.append(doc)

        except Exception as e:
            print(f"   ⚠️  文档读取失败: {e}")

        return docs

    def process_file(self, file_path: str, metadata: dict = None) -> List[LlamaDocument]:
        """
        自动识别文件类型并处理

        Args:
            file_path: 文件路径
            metadata: 额外的元数据

        Returns:
            LlamaDocument 列表
        """
        path = Path(file_path)

        if not path.exists():
            return []

        # 检查文件大小
        if path.stat().st_size > self.config.max_file_size:
            print(f"   ⚠️  文件过大，跳过: {path.name}")
            return []

        ext = path.suffix.lower()

        if ext == '.pdf':
            return self.process_pdf(str(path), metadata)
        elif ext in ['.docx', '.doc', '.xlsx', '.xls', '.pptx', '.md', '.txt', '.html']:
            return self.process_document(str(path), metadata)
        else:
            print(f"   ❓ 不支持的文件类型: {ext}")
            return []

    def parse_to_nodes(self, docs: List[LlamaDocument]) -> List:
        """将文档解析为节点"""
        nodes = []
        for doc in docs:
            doc_nodes = self.node_parser.get_nodes_from_documents([doc])
            nodes.extend(doc_nodes)
        return nodes

    def save_nodes(self, vector_store, nodes: List, progress: ProcessingProgress = None) -> int:
        """
        保存节点到向量存储

        Args:
            vector_store: 向量存储实例
            nodes: 节点列表
            progress: 进度记录

        Returns:
            成功保存的节点数
        """
        if not nodes:
            return 0

        saved = 0
        batch = []

        for node in nodes:
            if self.embed_model:
                try:
                    node.embedding = self.embed_model.get_text_embedding(node.get_content())
                    batch.append(node)
                except Exception as e:
                    print(f"\n   ⚠️  Embedding 失败: {e}")
                    continue
            else:
                batch.append(node)

            # 批量保存
            if len(batch) >= self.config.batch_size:
                try:
                    lance_store = vector_store._get_lance_vector_store()
                    lance_store.add(batch)
                    saved += len(batch)
                    batch = []
                except Exception as e:
                    print(f"\n   ⚠️  保存失败: {e}")

        # 保存剩余
        if batch:
            try:
                lance_store = vector_store._get_lance_vector_store()
                lance_store.add(batch)
                saved += len(batch)
            except Exception as e:
                print(f"\n   ⚠️  保存失败: {e}")

        if progress:
            progress.total_nodes += saved

        return saved

    def process_directory(
        self,
        directory: Path,
        vector_store,
        progress: ProcessingProgress = None,
        exclude_patterns: List[str] = None,
        recursive: bool = True,
        on_progress: Callable[[int, int, str], None] = None,
    ) -> dict:
        """
        处理整个目录

        Args:
            directory: 目录路径
            vector_store: 向量存储
            progress: 进度记录
            exclude_patterns: 排除的文件模式
            recursive: 是否递归
            on_progress: 进度回调 (current, total, filename)

        Returns:
            处理统计
        """
        exclude_patterns = exclude_patterns or [".DS_Store", "*.xls", "*.xlsx"]
        exclude_exts = {".xls", ".xlsx", ".DS_Store"}

        # 收集文件
        files = []
        if recursive:
            for f in directory.rglob("*"):
                if f.is_file():
                    if f.suffix.lower() in exclude_exts:
                        continue
                    if any(f.match(p) for p in exclude_patterns):
                        continue
                    files.append(f)
        else:
            for f in directory.glob("*"):
                if f.is_file():
                    if f.suffix.lower() in exclude_exts:
                        continue
                    files.append(f)

        if progress:
            progress.total_items = len(files)
            if not progress.started_at:
                progress.started_at = time.time()

        stats = {"files": 0, "failed": 0, "nodes": 0}

        for i, file_path in enumerate(files):
            if progress and str(file_path) in progress.processed_items:
                continue

            # 进度回调
            if on_progress:
                on_progress(i + 1, len(files), file_path.name)

            # 处理文件
            try:
                docs = self.process_file(str(file_path))
                if docs:
                    nodes = self.parse_to_nodes(docs)
                    saved = self.save_nodes(vector_store, nodes, progress)
                    stats["nodes"] += saved
                    stats["files"] += 1

                    if progress:
                        progress.processed_items.append(str(file_path))
                        progress.last_item = str(file_path)
            except Exception as e:
                print(f"   ⚠️  处理失败: {file_path.name} - {e}")
                stats["failed"] += 1
                if progress:
                    progress.failed_items.append(str(file_path))

        return stats
