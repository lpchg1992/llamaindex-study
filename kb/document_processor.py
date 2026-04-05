"""
通用文档处理器

提供统一的文档处理能力：
- PDF 扫描件检测
- PDF 转 Markdown (云端 OCR 服务: MinerU / doc2x)
- Office 文档处理 (Word, Excel, PPTX)
- 批量处理和增量保存
- 断点续传
- 增量更新（基于文件哈希）

供所有导入脚本使用
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, List, Callable, Set

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document as LlamaDocument
from llama_index.readers.file import PptxReader, PandasExcelReader
from llamaindex_study.node_parser import get_node_parser

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DocumentProcessorConfig:
    """文档处理器配置"""

    chunk_size: int = 1024
    chunk_overlap: int = 100
    chunk_strategy: str = "hierarchical"
    hierarchical_chunk_sizes: list = None
    batch_size: int = 50  # 每 N 个节点保存一次
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    pdf_scan_threshold: float = 10.0  # 文字密度阈值 (chars/sq inch)
    pdf_image_ratio_threshold: float = 0.8  # 图片比例阈值
    pdf_convert_timeout: int = 600  # PDF 转换超时 (秒)
    incremental: bool = True  # 增量更新模式

    def __post_init__(self):
        if self.hierarchical_chunk_sizes is None:
            from llamaindex_study.config import get_settings

            settings = get_settings()
            self.hierarchical_chunk_sizes = settings.hierarchical_chunk_sizes


@dataclass
class ProcessingProgress:
    """处理进度"""

    total_items: int = 0
    processed_items: List[str] = field(default_factory=list)
    skipped_items: List[str] = field(default_factory=list)
    failed_items: List[str] = field(default_factory=list)
    converted_files: dict = field(default_factory=dict)
    started_at: Optional[float] = None
    last_item: Optional[str] = None
    total_nodes: int = 0
    file_hashes: dict = field(default_factory=dict)

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
        self.node_parser = node_parser or get_node_parser(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
            strategy=self.config.chunk_strategy,
            hierarchical_chunk_sizes=self.config.hierarchical_chunk_sizes,
        )

    def set_embed_model(self, embed_model):
        """设置 embedding 模型"""
        self.embed_model = embed_model

    def _upsert_nodes(self, lance_store, nodes):
        """
        使用 lance_store.add() 写入节点，自动处理表创建

        Args:
            lance_store: LlamaIndex LanceDBVectorStore
            nodes: 节点列表
        """
        import logging

        add_logger = logging.getLogger("lancedb.add")

        # 获取 LanceDB 表的有效 metadata 字段列表
        valid_metadata_keys = self._get_valid_metadata_keys(lance_store)

        # 过滤每个节点的 metadata，只保留表 schema 中存在的字段
        for node in nodes:
            if hasattr(node, "metadata") and node.metadata:
                # 过滤掉不在 schema 中的字段
                node.metadata = {
                    k: v for k, v in node.metadata.items() if k in valid_metadata_keys
                }

        try:
            lance_store.add(nodes)
            add_logger.debug(f"添加 {len(nodes)} 节点")
        except Exception as e:
            add_logger.warning(f"添加失败，将重试: {e}")
            try:
                lance_store.add(nodes)
                add_logger.debug(f"重试成功，添加 {len(nodes)} 节点")
            except Exception as retry_err:
                add_logger.error(f"重试仍然失败: {retry_err}")
                raise

    def _get_valid_metadata_keys(self, lance_store) -> set:
        try:
            table = lance_store.table
            if table is None:
                return set()

            schema = table.schema

            for field in schema:
                if field.name == "metadata":
                    struct_type = field.type
                    valid_keys = set()
                    for i in range(struct_type.num_fields):
                        valid_keys.add(struct_type.field(i).name)
                    return valid_keys

            return set()
        except Exception:
            return set()

    @staticmethod
    def compute_file_hash(file_path: str) -> str:
        """
        计算文件的 MD5 哈希值

        Args:
            file_path: 文件路径

        Returns:
            MD5 哈希值字符串
        """
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                # 只读取前 1MB 用于快速哈希
                chunk = f.read(1024 * 1024)
                hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return ""

    def is_file_changed(
        self, file_path: str, progress: ProcessingProgress = None
    ) -> bool:
        """
        检查文件是否已修改（用于增量更新）

        Args:
            file_path: 文件路径
            progress: 进度记录

        Returns:
            True 如果文件已修改或新文件，需要处理
        """
        if not self.config.incremental:
            return True

        current_hash = self.compute_file_hash(file_path)
        if not current_hash:
            return True

        # 检查是否是新文件或已修改
        if file_path not in (progress.file_hashes if progress else {}):
            return True

        return progress.file_hashes.get(file_path) != current_hash

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
                chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
                english_chars = len(re.findall(r"[a-zA-Z]", text))
                number_chars = len(re.findall(r"[0-9]", text))
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
                            1
                            for obj in xobjects.values()
                            if obj.get("/Subtype") == "/Image"
                        )
                        if image_count > 0:
                            image_pages += 1
                except Exception:
                    pass

            if image_pages / pages_to_check > self.config.pdf_image_ratio_threshold:
                return True

            return False

        except Exception as e:
            print(f"   ⚠️  PDF 检测失败: {e}")
            return True  # 保守处理

    def convert_pdf_to_markdown(
        self, pdf_path: str, timeout: int = None
    ) -> Optional[str]:
        """将 PDF 转换为 Markdown"""
        timeout = timeout or self.config.pdf_convert_timeout
        print(f"   🔄 正在转换 PDF 为 Markdown...")

        file_size_mb, page_count = self._get_pdf_info(pdf_path)
        need_split = file_size_mb >= 200 or page_count >= 600

        if need_split:
            print(f"   📄 文件过大 ({file_size_mb:.1f}MB, {page_count}页)，开始拆分...")
            chunk_files = self._split_pdf_to_temp(pdf_path, pages_per_chunk=500)
            if not chunk_files:
                print(f"   ❌ PDF 拆分失败")
                return None

            all_text = []
            for i, chunk_path in enumerate(chunk_files):
                print(
                    f"   📄 处理第 {i + 1}/{len(chunk_files)} 部分 ({chunk_path.name})..."
                )
                chunk_text = self._convert_single_pdf(chunk_path, timeout)
                if chunk_text:
                    all_text.append(chunk_text)
                else:
                    all_text.append(f"[Part {i + 1}: OCR failed]")

                try:
                    chunk_path.unlink()
                except Exception:
                    pass

            if all_text:
                combined = "\n\n---\n\n".join(all_text)
                if len(combined.strip()) > 100:
                    print(f"   ✅ 拆分转换完成 ({len(chunk_files)} parts)")
                    return combined
            return None

        return self._convert_single_pdf(pdf_path, timeout)

    def _convert_single_pdf(self, pdf_path: str, timeout: int = None) -> Optional[str]:
        """转换单个 PDF（不拆分）"""
        from llamaindex_study.config import get_settings

        settings = get_settings()

        mineru_api_key = getattr(settings, "mineru_api_key", None) or os.getenv(
            "MINERU_API_KEY"
        )
        mineru_pipeline_id = getattr(settings, "mineru_pipeline_id", None) or os.getenv(
            "MINERU_PIPELINE_ID"
        )

        if mineru_api_key and mineru_pipeline_id:
            print(f"   ☁️  策略1: MinerU...")
            md = self._convert_pdf_mineru(
                pdf_path, mineru_api_key, mineru_pipeline_id, timeout
            )
            if md:
                return md
        else:
            print(f"   ⏭️  策略1: MinerU 未配置")

        doc2x_api_key = getattr(settings, "doc2x_api_key", None) or os.getenv(
            "DOC2X_API_KEY"
        )

        if doc2x_api_key:
            print(f"   ☁️  策略2: doc2x...")
            md = self._convert_pdf_doc2x(pdf_path, doc2x_api_key, timeout)
            if md:
                return md
        else:
            print(f"   ⏭️  策略2: doc2x 未配置")

        print(f"   ❌ 所有 OCR 策略均失败")
        return None

    def _convert_pdf_mineru(
        self, pdf_path: str, api_key: str, pipeline_id: str, timeout: int = None
    ) -> Optional[str]:
        """使用 MinerU API 转换 PDF

        Args:
            pdf_path: PDF 文件路径
            api_key: MinerU API Key
            pipeline_id: MinerU Pipeline ID
            timeout: 超时时间

        Returns:
            Markdown 内容，失败返回 None
        """
        try:
            import requests

            base_url = "https://mineru.net/api/kie"
            headers = {"Authorization": f"Bearer {api_key}"}

            with open(pdf_path, "rb") as f:
                files = {"file": (Path(pdf_path).name, f, "application/pdf")}
                data = {"pipeline_id": pipeline_id}
                resp = requests.post(
                    f"{base_url}/upload",
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=timeout or 60,
                )

            if resp.status_code != 200:
                print(f"   ⚠️  MinerU 上传失败: {resp.status_code}")
                return None

            file_ids = resp.json().get("file_ids", [])
            if not file_ids:
                print(f"   ⚠️  MinerU 无返回 file_ids")
                return None

            poll_interval = 5
            max_polls = (timeout or 600) // poll_interval
            for _ in range(max_polls):
                result_resp = requests.get(
                    f"{base_url}/result/{file_ids[0]}",
                    headers=headers,
                    timeout=30,
                )
                if result_resp.status_code == 200:
                    result = result_resp.json()
                    status = result.get("status", "")
                    if status == "completed":
                        content = result.get("content", "")
                        if content and len(content.strip()) > 100:
                            print(f"   ✅ MinerU 转换成功")
                            return content
                        elif status == "failed":
                            print(f"   ⚠️  MinerU 处理失败")
                            return None
                time.sleep(poll_interval)

            print(f"   ⚠️  MinerU 轮询超时")
            return None

        except ImportError:
            print(f"   ⚠️  MinerU 需要 requests 库")
        except Exception as e:
            print(f"   ⚠️  MinerU 失败: {e}")

        return None

    def _convert_pdf_doc2x(
        self, pdf_path: str, api_key: str, timeout: int = None
    ) -> Optional[str]:
        """使用 doc2x MCP 转换 PDF

        Args:
            pdf_path: PDF 文件路径
            api_key: doc2x API Key
            timeout: 超时时间

        Returns:
            Markdown 内容，失败返回 None
        """
        timeout = timeout or self.config.pdf_convert_timeout
        proc = None

        try:
            proc = subprocess.Popen(
                ["npx", "-y", "@noedgeai-org/doc2x-mcp@latest"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "DOC2X_API_KEY": api_key},
            )

            init_msg = {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "llamaindex-study", "version": "0.1"},
                },
            }

            tool_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_parse_pdf_wait_text",
                    "arguments": {"pdf_path": pdf_path},
                },
            }

            import threading

            result_holder = {"result": None, "error": None}

            def read_stdout():
                try:
                    buffer = ""
                    while True:
                        char = proc.stdout.read(1)
                        if not char:
                            break
                        buffer += char
                        if char == "\n":
                            line = buffer.strip()
                            buffer = ""
                            if not line:
                                continue
                            try:
                                resp = json.loads(line)
                                if resp.get("id") == 1 and "result" in resp:
                                    content = resp["result"].get("content", [])
                                    if isinstance(content, list) and len(content) > 0:
                                        text = content[0].get("text", "")
                                        if text and len(text.strip()) > 100:
                                            result_holder["result"] = text
                                            return
                            except json.JSONDecodeError:
                                continue
                except Exception as e:
                    result_holder["error"] = str(e)

            reader_thread = threading.Thread(target=read_stdout)
            reader_thread.daemon = True
            reader_thread.start()

            proc.stdin.write(json.dumps(init_msg) + "\n")
            proc.stdin.flush()

            import time

            start_time = time.time()
            while reader_thread.is_alive() and (time.time() - start_time) < 5:
                time.sleep(0.1)

            if result_holder["result"]:
                proc.stdin.write(json.dumps(tool_msg) + "\n")
                proc.stdin.flush()

                reader_thread.join(timeout=timeout)
                if result_holder["result"]:
                    print(f"   ✅ doc2x 转换成功")
                    return result_holder["result"]
            else:
                time.sleep(2)

                proc.stdin.write(json.dumps(tool_msg) + "\n")
                proc.stdin.flush()

                reader_thread.join(timeout=timeout)
                if result_holder["result"]:
                    print(f"   ✅ doc2x 转换成功")
                    return result_holder["result"]

            if result_holder["error"]:
                print(f"   ⚠️  doc2x 读取错误: {result_holder['error']}")

            if proc:
                proc.terminate()
            return result_holder.get("result")

        except subprocess.TimeoutExpired:
            print(f"   ❌ doc2x 转换超时")
            if proc:
                proc.kill()
        except Exception as e:
            print(f"   ⚠️  doc2x 失败: {e}")

        return None

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

        is_scanned = self.is_scanned_pdf(pdf_path)

        if is_scanned:
            print(f"   🔍 检测为扫描件，尝试 OCR 转换...")
            md_content = self.convert_pdf_to_markdown(pdf_path)
            if md_content:
                md_save_dir = Path("/Volumes/online/llamaindex/mddocs")
                md_save_dir.mkdir(parents=True, exist_ok=True)
                md_file_name = Path(pdf_path).stem + ".md"
                md_file_path = md_save_dir / md_file_name
                with open(md_file_path, "w", encoding="utf-8") as f:
                    f.write(md_content)
                print(f"   💾 Markdown 已保存: {md_file_path}")

                doc = LlamaDocument(
                    text=md_content,
                    metadata={
                        "source": "pdf_scanned",
                        "file_path": pdf_path,
                        "converted": True,
                        "md_file_path": str(md_file_path),
                        **(metadata or {}),
                    },
                )
                docs.append(doc)
            else:
                try:
                    reader = SimpleDirectoryReader(input_files=[pdf_path])
                    raw_docs = reader.load_data()
                    for doc in raw_docs:
                        if len(doc.text.strip()) > 500:
                            doc.metadata["source"] = "pdf_partial"
                            doc.metadata.update(metadata or {})
                            docs.append(doc)
                except Exception:
                    pass
        else:
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

    def _split_pdf_to_temp(
        self, pdf_path: str, pages_per_chunk: int = 500
    ) -> List[Path]:
        """将大型 PDF 拆分为临时文件

        Args:
            pdf_path: PDF 文件路径
            pages_per_chunk: 每块页数

        Returns:
            临时 PDF 文件路径列表
        """
        import fitz

        temp_dir = Path(tempfile.gettempdir()) / "llamaindex_pdf_split"
        temp_dir.mkdir(parents=True, exist_ok=True)

        temp_files = []
        pdf_name = Path(pdf_path).stem

        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)

            for start in range(0, total_pages, pages_per_chunk):
                end = min(start + pages_per_chunk, total_pages)
                new_doc = fitz.open()
                for page_num in range(start, end):
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)

                chunk_path = temp_dir / f"{pdf_name}_p{start + 1}-{end}.pdf"
                new_doc.save(str(chunk_path))
                new_doc.close()
                temp_files.append(chunk_path)

            doc.close()
            print(f"   📄 PDF 已拆分为 {len(temp_files)} 个部分")
        except Exception as e:
            print(f"   ⚠️  PDF 拆分失败: {e}")

        return temp_files

    def _get_pdf_info(self, pdf_path: str) -> tuple:
        """获取 PDF 信息

        Returns:
            (file_size_mb, page_count)
        """
        file_size_mb = Path(pdf_path).stat().st_size / (1024 * 1024)
        try:
            import fitz

            doc = fitz.open(pdf_path)
            page_count = len(doc)
            doc.close()
        except Exception:
            page_count = 0
        return file_size_mb, page_count

    def process_document(
        self, file_path: str, metadata: dict = None
    ) -> List[LlamaDocument]:
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

        source_map = {
            ".docx": "word",
            ".doc": "word",
            ".xlsx": "excel",
            ".xls": "excel",
            ".pptx": "pptx",
            ".md": "markdown",
            ".txt": "text",
            ".html": "html",
        }

        try:
            # Excel 和 PowerPoint 需要使用专门的 Reader
            if ext in [".xlsx", ".xls"]:
                reader = PandasExcelReader()
                raw_docs = reader.load_data(str(path))
                logger.debug(
                    f"使用 PandasExcelReader 读取 {path}, 获取 {len(raw_docs)} 个文档"
                )
            elif ext == ".pptx":
                reader = PptxReader()
                raw_docs = reader.load_data(str(path))
                logger.debug(
                    f"使用 PptxReader 读取 {path}, 获取 {len(raw_docs)} 个文档"
                )
            else:
                reader = SimpleDirectoryReader(input_files=[str(path)])
                raw_docs = reader.load_data()
                logger.debug(
                    f"使用 SimpleDirectoryReader 读取 {path}, 获取 {len(raw_docs)} 个文档"
                )

            source = source_map.get(ext, "document")

            for doc in raw_docs:
                doc.metadata["source"] = source
                doc.metadata["file_path"] = str(path)
                doc.metadata.update(metadata or {})
                docs.append(doc)

            logger.info(f"文档处理成功: {path}, 类型={source}, 文档数={len(docs)}")

        except Exception as e:
            logger.error(f"文档读取失败: {path}, 错误: {e}")
            raise

        return docs

    def process_file(
        self, file_path: str, metadata: dict = None
    ) -> List[LlamaDocument]:
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

        if ext == ".pdf":
            return self.process_pdf(str(path), metadata)
        elif ext in [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".md", ".txt", ".html"]:
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

    def save_nodes(
        self, vector_store, nodes: List, progress: ProcessingProgress = None
    ) -> int:
        """
        保存节点到向量存储

        使用批量 embedding 优化性能。

        Args:
            vector_store: 向量存储实例
            nodes: 节点列表
            progress: 进度记录

        Returns:
            成功保存的节点数
        """
        if not nodes:
            return 0

        # 优先使用批量 embedding
        from llamaindex_study.ollama_utils import BatchEmbeddingHelper

        batch_helper = BatchEmbeddingHelper(
            embed_model=self.embed_model, batch_size=self.config.batch_size
        )

        saved = 0
        processed_batch = []

        processed_batch = list(nodes)

        # 批量处理
        if processed_batch and self.embed_model:
            texts = [node.get_content() for node in processed_batch]
            try:
                embeddings = batch_helper.embed_documents(texts)
                for node, embedding in zip(processed_batch, embeddings):
                    node.embedding = embedding
            except Exception as e:
                print(f"\n   ⚠️  批量 Embedding 失败: {e}")
                # 回退到逐个 embedding
                for node in processed_batch:
                    try:
                        node.embedding = self.embed_model.get_text_embedding(
                            node.get_content()
                        )
                    except Exception as ex:
                        print(f"      ⚠️  Embedding 失败: {ex}")
                        processed_batch.remove(node)

        # 保存所有节点
        try:
            lance_store = vector_store._get_lance_vector_store()
            self._upsert_nodes(lance_store, processed_batch)
            saved = len(processed_batch)
        except Exception as e:
            raise RuntimeError(f"向量数据库写入失败: {e}")

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
