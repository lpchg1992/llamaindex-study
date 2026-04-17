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

==============================================================================
临时性修复代码备注 (2026-04-06)
==============================================================================
本文件包含用于修复 doc2x 导出截断问题的临时性代码：

1. _extract_truncated_info() 和 _doc2x_export_full_markdown_from_uid()
   - 用途：从截断的 md 文件中提取 UID，使用 doc2x 的导出接口获取完整内容
   - 触发条件：md 文件包含 "Output truncated" 标记
   - 不消耗 OCR 额度：直接使用已存在的 UID 导出

2. _convert_pdf_mineru() 已迁移到 MinerU v4 API
   - 原因：v1 API 已弃用
   - 迁移时间：2026-04-06

这些代码在正常业务流程中不会被执行，仅在检测到截断文件时调用。
当所有截断文件被修复并重新导入后，这些代码可以保留（不会影响正常流程）
或删除（如果确认不再需要）。
==============================================================================
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional, List, Callable

from llama_index.core import SimpleDirectoryReader
from llama_index.core.schema import Document as LlamaDocument
from llama_index.readers.file import PptxReader, PandasExcelReader
from llama_index.core.node_parser import HierarchicalNodeParser

from rag.logger import get_logger

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
            from rag.config import get_settings

            settings = get_settings()
            self.hierarchical_chunk_sizes = settings.hierarchical_chunk_sizes


@dataclass
class ConversionMetadata:
    """文档转换元数据，存储在 {md_file}.meta.json"""

    uid: Optional[str] = None
    mineru_batch_id: Optional[str] = None
    is_truncated: bool = False
    converted_at: Optional[str] = None
    source_pdf: Optional[str] = None
    page_count: int = 0

    def save(self, md_path: Path) -> None:
        meta_path = md_path.with_suffix(".meta.json")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, md_path: Path) -> Optional["ConversionMetadata"]:
        meta_path = md_path.with_suffix(".meta.json")
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    return cls(**json.load(f))
            except Exception:
                pass
        return None

    def delete(self, md_path: Path) -> None:
        meta_path = md_path.with_suffix(".meta.json")
        if meta_path.exists():
            meta_path.unlink()


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
        self.node_parser = node_parser
        if self.node_parser is None:
            chunk_sizes = self.config.hierarchical_chunk_sizes
            if chunk_sizes is None:
                from rag.config import get_settings
                settings = get_settings()
                chunk_sizes = settings.hierarchical_chunk_sizes
            self.node_parser = HierarchicalNodeParser.from_defaults(
                chunk_sizes=chunk_sizes,
                chunk_overlap=self.config.chunk_overlap,
                include_metadata=True,
                include_prev_next_rel=True,
            )

    def set_embed_model(self, embed_model):
        """设置 embedding 模型"""
        self.embed_model = embed_model

    def _upsert_nodes(self, lance_store, nodes):
        import logging
        import pyarrow as pa
        from llama_index.core.vector_stores.utils import node_to_metadata_dict

        add_logger = logging.getLogger("lancedb.add")

        valid_meta_keys = self._get_valid_metadata_keys(lance_store)

        data = []
        skipped = 0
        failed_ids = []
        doc_ids = set()
        for node in nodes:
            if not hasattr(node, "embedding") or node.embedding is None:
                skipped += 1
                failed_ids.append(node.node_id)
                continue
            if isinstance(node.embedding, (list, tuple)) and len(node.embedding) > 0:
                if all(v == 0.0 for v in node.embedding):
                    skipped += 1
                    failed_ids.append(node.node_id)
                    continue
            metadata_dict = node_to_metadata_dict(
                node, remove_text=False, flat_metadata=True
            )
            if valid_meta_keys:
                metadata_dict = {
                    k: v for k, v in metadata_dict.items() if k in valid_meta_keys
                }
            doc_id = node.ref_doc_id if hasattr(node, "ref_doc_id") else None
            if doc_id:
                doc_ids.add(doc_id)
            row = {
                "id": node.node_id,
                "doc_id": doc_id,
                "text": node.get_content(),
                "vector": node.embedding,
                "metadata": metadata_dict,
            }
            data.append(row)

        if not data:
            return (0, skipped, failed_ids)

        df = pa.Table.from_pylist(data)

        table = None
        try:
            table = lance_store._connection.open_table(lance_store._table_name)
        except Exception:
            pass

        if table is None:
            lance_store._connection.create_table(
                lance_store._table_name, df, mode="create"
            )
            add_logger.debug(f"创建新表并插入 {len(data)} 节点")
        else:
            try:
                if doc_ids:
                    doc_ids_str = " OR ".join(
                        [f"doc_id = '{did}'" for did in doc_ids if did]
                    )
                    if doc_ids_str:
                        try:
                            delete_result = table.delete(f"{doc_ids_str}")
                            deleted_count = getattr(delete_result, "num_deleted", 0)
                            if deleted_count > 0:
                                add_logger.debug(
                                    f"删除 {deleted_count} 个已存在的节点 (doc_id 去重)"
                                )
                        except Exception as delete_err:
                            add_logger.warning(f"删除旧节点失败: {delete_err}")
                (table.merge_insert("id").when_not_matched_insert_all().execute(df))
                add_logger.debug(f"UPSERT {len(data)} 节点 (按 doc_id 去重)")
            except Exception as e:
                add_logger.warning(f"UPSERT 失败，回退到追加写入: {e}")
                table.add(data)

        return (len(data), skipped, failed_ids)

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
        3. 综合判断：只有同时满足"低密度"和"高图片比例"才认为是扫描件
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

            image_ratio = image_pages / pages_to_check

            if avg_density < 10 and image_ratio > 0.7:
                return True

            if avg_density < 30 and image_ratio > 0.5:
                return True

            if avg_density < self.config.pdf_scan_threshold and image_ratio > 0.5:
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

        md_file_path = (
            Path("/Volumes/online/llamaindex/mddocs") / f"{Path(pdf_path).stem}.md"
        )

        if md_file_path.exists() and md_file_path.stat().st_size > 100:
            meta = ConversionMetadata.load(md_file_path)
            if meta and not meta.is_truncated:
                print(f"   📄 本地 MD 已存在且完整，跳过转换: {md_file_path.name}")
                try:
                    return md_file_path.read_text(encoding="utf-8")
                except Exception:
                    pass
            elif meta and meta.is_truncated:
                print(f"   📄 本地 MD 存在但被截断，将重新转换")

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
        md_file_path = (
            Path("/Volumes/online/llamaindex/mddocs") / f"{Path(pdf_path).stem}.md"
        )
        if md_file_path.exists() and md_file_path.stat().st_size > 100:
            print(f"   📄 本地 md 已存在，跳过云端转换: {md_file_path.name}")
            try:
                return md_file_path.read_text(encoding="utf-8")
            except Exception:
                pass

        from rag.config import get_settings

        settings = get_settings()

        mineru_api_key = getattr(settings, "mineru_api_key", None) or os.getenv(
            "MINERU_API_KEY"
        )
        mineru_pipeline_id = getattr(settings, "mineru_pipeline_id", None) or os.getenv(
            "MINERU_PIPELINE_ID"
        )

        mineru_truncated = False

        if mineru_api_key and mineru_pipeline_id:
            print(f"   ☁️  MinerU...")
            md, mineru_truncated = self._convert_pdf_mineru(
                pdf_path, mineru_api_key, mineru_pipeline_id, timeout
            )
            if md:
                self._save_md_to_local(md, pdf_path)
                return md
        else:
            print(f"   ⏭️  MinerU 未配置，跳过")

        if mineru_truncated:
            doc2x_api_key = getattr(settings, "doc2x_api_key", None) or os.getenv(
                "DOC2X_API_KEY"
            )

            if doc2x_api_key:
                print(f"   ☁️  doc2x (备用)...")
                md = self._convert_pdf_doc2x(pdf_path, doc2x_api_key, timeout)
                if md:
                    self._save_md_to_local(md, pdf_path, mineru_truncated=True)
                    return md
            else:
                print(f"   ⏭️  doc2x 未配置，跳过")

            print(f"   ❌ MinerU 截断且 doc2x 失败")
            return None

        print(f"   ❌ 所有转换策略均失败")
        return None

    def _save_md_to_local(
        self, md_content: str, pdf_path: str, mineru_truncated: bool = False
    ) -> None:
        """保存 md 内容到本地"""
        md_save_dir = Path("/Volumes/online/llamaindex/mddocs")
        md_save_dir.mkdir(parents=True, exist_ok=True)
        md_file_path = md_save_dir / f"{Path(pdf_path).stem}.md"
        try:
            md_file_path.write_text(md_content, encoding="utf-8")
            print(f"   💾 Markdown 已保存: {md_file_path}")
        except Exception as e:
            print(f"   ⚠️  保存 md 失败: {e}")

        if mineru_truncated:
            meta = ConversionMetadata(
                is_truncated=False,
                source_pdf=str(pdf_path),
            )
            meta.save(md_file_path)

    def _convert_pdf_mineru(
        self, pdf_path: str, api_key: str, pipeline_id: str, timeout: int = None
    ) -> tuple:
        """使用 MinerU 精准解析 API 转换 PDF

        Args:
            pdf_path: PDF 文件路径
            api_key: MinerU API Key
            pipeline_id: MinerU Pipeline ID (用于兼容旧接口，此参数不再使用)
            timeout: 超时时间

        Returns:
            Markdown 内容，失败返回 None
        """
        try:
            import io
            import zipfile

            import requests

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

            file_name = Path(pdf_path).name
            batch_url = "https://mineru.net/api/v4/file-urls/batch"

            batch_resp = requests.post(
                batch_url,
                headers=headers,
                json={
                    "files": [{"name": file_name, "data_id": file_name}],
                    "model_version": "pipeline",
                },
                timeout=30,
            )

            if batch_resp.status_code != 200:
                print(f"   ⚠️  MinerU 获取上传链接失败: {batch_resp.status_code}")
                return (None, False)

            batch_data = batch_resp.json()
            if batch_data.get("code") != 0:
                print(f"   ⚠️  MinerU API 错误: {batch_data.get('msg')}")
                return (None, False)

            batch_id = batch_data.get("data", {}).get("batch_id")
            file_urls = batch_data.get("data", {}).get("file_urls", [])
            if not file_urls:
                print(f"   ⚠️  MinerU 无返回上传链接")
                return (None, False)

            upload_url = file_urls[0]
            print(f"   📤 正在上传 PDF 到 MinerU...")

            with open(pdf_path, "rb") as f:
                upload_resp = requests.put(upload_url, data=f, timeout=60)

            if upload_resp.status_code not in (200, 201):
                print(f"   ⚠️  MinerU 文件上传失败: {upload_resp.status_code}")
                return (None, False)

            print(f"   🔄 MinerU 正在解析 PDF (batch_id={batch_id[:8]}...)")

            poll_interval = 5
            max_wait = timeout or 600
            start_time = time.time()
            interval = 5
            max_interval = 30

            while time.time() - start_time < max_wait:
                result_resp = requests.get(
                    f"https://mineru.net/api/v4/extract-results/batch/{batch_id}",
                    headers=headers,
                    timeout=30,
                )
                if result_resp.status_code == 200:
                    result = result_resp.json()
                    if result.get("code") == 0:
                        extract_results = result.get("data", {}).get(
                            "extract_result", []
                        )
                        for extract_result in extract_results:
                            state = extract_result.get("state", "")
                            if state == "done":
                                full_zip_url = extract_result.get("full_zip_url")
                                if full_zip_url:
                                    print(f"   📥 正在下载 MinerU 结果...")
                                    zip_resp = requests.get(full_zip_url, timeout=120)
                                    if zip_resp.status_code == 200:
                                        zip_data = zip_resp.content
                                        with zipfile.ZipFile(
                                            io.BytesIO(zip_data)
                                        ) as zf:
                                            md_content = zf.read("full.md").decode(
                                                "utf-8"
                                            )

                                            if "Output truncated" in md_content:
                                                md_file_path = (
                                                    Path(
                                                        "/Volumes/online/llamaindex/mddocs"
                                                    )
                                                    / f"{Path(pdf_path).stem}.md"
                                                )
                                                meta = ConversionMetadata(
                                                    is_truncated=True,
                                                    source_pdf=str(pdf_path),
                                                )
                                                meta.save(md_file_path)
                                                if md_file_path.exists():
                                                    md_file_path.unlink()
                                                print(
                                                    f"   ⚠️  MinerU 截断，删除 MD 并触发 doc2x fallback"
                                                )
                                                return (None, True)

                                            images_dir = Path(
                                                "/Volumes/online/llamaindex/mddocs/images"
                                            )
                                            for name in zf.namelist():
                                                if name.startswith(
                                                    "images/"
                                                ) and not name.endswith("/"):
                                                    img_data = zf.read(name)
                                                    img_name = Path(name).name
                                                    img_path = images_dir / img_name
                                                    img_path.parent.mkdir(
                                                        parents=True, exist_ok=True
                                                    )
                                                    img_path.write_bytes(img_data)

                                            md_file_path = (
                                                Path(
                                                    "/Volumes/online/llamaindex/mddocs"
                                                )
                                                / f"{Path(pdf_path).stem}.md"
                                            )
                                            meta = ConversionMetadata(
                                                mineru_batch_id=batch_id,
                                                is_truncated=False,
                                            )
                                            meta.save(md_file_path)

                                            print(
                                                f"   ✅ MinerU 转换成功 ({len(md_content)} chars)"
                                            )
                                            return (md_content, False)
                                    else:
                                        print(
                                            f"   ⚠️  MinerU 结果下载失败: {zip_resp.status_code}"
                                        )
                            elif state == "failed":
                                err_msg = extract_result.get("err_msg", "未知错误")
                                print(f"   ⚠️  MinerU 处理失败: {err_msg}")
                                return (None, False)
                time.sleep(interval)
                interval = min(interval * 1.5, max_interval)

            print(f"   ⚠️  MinerU 轮询超时")
            return (None, False)

        except ImportError:
            print(f"   ⚠️  MinerU 需要 requests 库")
        except Exception as e:
            print(f"   ⚠️  MinerU 失败: {e}")

        return (None, False)

    def _extract_truncated_info(self, md_content: str) -> Optional[dict]:
        """从截断的 md 内容中提取 UID 和页数信息

        Args:
            md_content: md 文件内容

        Returns:
            dict: {"uid": "...", "pages_done": N, "pages_total": M} 或 None
        """
        import re

        pattern = r"Output truncated \(pages (\d+)/(\d+), uid=([a-f0-9\-]+)\)"
        match = re.search(pattern, md_content)
        if match:
            return {
                "pages_done": int(match.group(1)),
                "pages_total": int(match.group(2)),
                "uid": match.group(3),
            }
        return None

    def _doc2x_export_full_markdown_from_uid(
        self, uid: str, api_key: str, timeout: int = None
    ) -> Optional[str]:
        """使用已有 UID 导出完整 markdown（不消耗 OCR 额度）

        工作流程：
        1. doc2x_convert_export_submit - 提交导出任务
        2. doc2x_convert_export_wait - 等待导出完成
        3. 下载 zip 文件并提取 markdown 和图片

        Args:
            uid: 之前 OCR 生成的 UID
            api_key: doc2x API Key
            timeout: 超时时间

        Returns:
            完整 Markdown 内容，失败返回 None
        """
        import io
        import urllib.request
        import urllib.error
        import zipfile

        timeout = timeout or self.config.pdf_convert_timeout
        proc = None

        try:
            proc = subprocess.Popen(
                ["node", "/tmp/doc2x_mcp/node_modules/.bin/doc2x-mcp"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ,
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

            proc.stdin.write(json.dumps(init_msg) + "\n")
            proc.stdin.flush()
            time.sleep(2)

            submit_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_convert_export_submit",
                    "arguments": {"uid": uid, "to": "md", "formula_mode": "normal"},
                },
            }
            proc.stdin.write(json.dumps(submit_msg) + "\n")
            proc.stdin.flush()

            submit_done = False
            submit_start = time.time()
            while time.time() - submit_start < 60:
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                try:
                    resp = json.loads(line.strip())
                    if resp.get("id") == 1 and "result" in resp:
                        submit_done = True
                        break
                except json.JSONDecodeError:
                    continue
                time.sleep(0.5)

            if not submit_done:
                print(f"   ⚠️  doc2x 导出提交超时")
                proc.terminate()
                return None

            wait_msg = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_convert_export_wait",
                    "arguments": {"uid": uid, "to": "md", "poll_interval": 5000},
                },
            }
            proc.stdin.write(json.dumps(wait_msg) + "\n")
            proc.stdin.flush()

            export_url = None
            start_time = time.time()
            interval = 2
            max_wait = min(timeout, 600)

            while time.time() - start_time < max_wait:
                line = proc.stdout.readline()
                if not line:
                    time.sleep(interval)
                    interval = min(interval * 1.5, 20)
                    continue
                try:
                    resp = json.loads(line.strip())
                    if resp.get("id") == 2 and "result" in resp:
                        result = resp["result"]
                        if isinstance(result, dict):
                            content = result.get("content", [])
                            if content:
                                text = content[0].get("text", "")
                                if text:
                                    try:
                                        data = json.loads(text)
                                        url = data.get("url")
                                        if url and data.get("status") == "success":
                                            export_url = url
                                            break
                                        if data.get("status") == "failed":
                                            print(f"   ⚠️  doc2x 导出失败")
                                            break
                                    except json.JSONDecodeError:
                                        pass
                except json.JSONDecodeError:
                    pass
                time.sleep(interval)
                interval = min(interval * 1.5, 20)

            proc.terminate()

            if export_url:
                print(f"   📥 正在从 URL 下载完整 markdown...")
                try:
                    req = urllib.request.Request(export_url)
                    with urllib.request.urlopen(req, timeout=120) as response:
                        zip_data = response.read()
                        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                            md_content = zf.read("output.md").decode("utf-8")
                            images_dir = Path(
                                "/Volumes/online/llamaindex/mddocs/images"
                            )
                            for name in zf.namelist():
                                if name.startswith("images/") and not name.endswith(
                                    "/"
                                ):
                                    img_data = zf.read(name)
                                    img_name = Path(name).name
                                    img_path = images_dir / img_name
                                    img_path.parent.mkdir(parents=True, exist_ok=True)
                                    img_path.write_bytes(img_data)
                            print(f"   ✅ doc2x 完整导出成功 ({len(md_content)} chars)")
                            return md_content
                except Exception as e:
                    print(f"   ⚠️  下载失败: {e}")

            return None

        except Exception as e:
            print(f"   ⚠️  doc2x 导出失败: {e}")
            if proc:
                proc.kill()
        return None

    def _doc2x_parse_and_export_full(
        self, pdf_path: str, api_key: str, timeout: int = None
    ) -> Optional[str]:
        """使用 doc2x MCP 完整解析并导出 PDF（包含完整 markdown）

        工作流程：
        1. doc2x_parse_pdf_submit - 提交解析任务
        2. doc2x_parse_pdf_status - 轮询等待解析完成
        3. doc2x_convert_export_submit - 提交导出任务
        4. doc2x_convert_export_wait - 等待导出完成
        5. 下载 zip 文件并提取 markdown 和图片

        Args:
            pdf_path: PDF 文件路径
            api_key: doc2x API Key
            timeout: 超时时间

        Returns:
            完整 Markdown 内容，失败返回 None
        """
        import io
        import urllib.request
        import urllib.error
        import zipfile

        timeout = timeout or self.config.pdf_convert_timeout
        proc = None

        def read_mcp_response(proc, timeout_sec=30):
            start = time.time()
            while time.time() - start < timeout_sec:
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                try:
                    return json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
            return None

        def poll_until_done(
            proc,
            status_msg,
            check_done,
            timeout_sec,
            initial_interval=2,
            max_interval=30,
        ):
            interval = initial_interval
            max_polls = max(timeout_sec // initial_interval, 10)
            for _ in range(max_polls):
                proc.stdin.write(json.dumps(status_msg) + "\n")
                proc.stdin.flush()

                resp = read_mcp_response(proc, timeout_sec=10)
                if resp and "result" in resp:
                    done, should_retry = check_done(resp)
                    if done:
                        return True, None
                    if not should_retry:
                        return False, "任务失败"
                    # 失败但可重试，继续等待

                time.sleep(interval)
                interval = min(interval * 1.5, max_interval)

            return False, "轮询超时"

        try:
            proc = subprocess.Popen(
                ["node", "/tmp/doc2x_mcp/node_modules/.bin/doc2x-mcp"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=os.environ,
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

            proc.stdin.write(json.dumps(init_msg) + "\n")
            proc.stdin.flush()
            time.sleep(2)

            submit_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_parse_pdf_submit",
                    "arguments": {"pdf_path": pdf_path},
                },
            }
            proc.stdin.write(json.dumps(submit_msg) + "\n")
            proc.stdin.flush()

            start_time = time.time()
            uid = None
            uid_timeout = min(timeout // 2, 120)
            while time.time() - start_time < uid_timeout:
                resp = read_mcp_response(proc, timeout_sec=5)
                if resp and resp.get("id") == 1 and "result" in resp:
                    result = resp["result"]
                    if isinstance(result, dict):
                        uid = result.get("uid")
                        if uid:
                            break
                time.sleep(0.5)

            if not uid:
                print(f"   ⚠️  无法获取 UID (等待超时)")
                proc.terminate()
                return None

            print(f"   🔄 doc2x 正在解析 PDF (uid={uid})...")

            status_msg = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_parse_pdf_status",
                    "arguments": {"uid": uid},
                },
            }

            def check_parse_done(resp):
                result = resp.get("result", {})
                if isinstance(result, dict):
                    content = result.get("content", [])
                    if content:
                        text = content[0].get("text", "")
                        if text:
                            try:
                                data = json.loads(text)
                                status = data.get("status", "")
                                if status == "success":
                                    return True, None
                                if status == "failed":
                                    return False, False
                            except json.JSONDecodeError:
                                pass
                return False, True

            parse_done, parse_err = poll_until_done(
                proc, status_msg, check_parse_done, timeout_sec=min(timeout, 600)
            )

            if not parse_done:
                print(f"   ⚠️  doc2x parse 状态检查失败: {parse_err}")
                proc.terminate()
                return None

            export_submit_msg = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_convert_export_submit",
                    "arguments": {"uid": uid, "to": "md", "formula_mode": "normal"},
                },
            }
            proc.stdin.write(json.dumps(export_submit_msg) + "\n")
            proc.stdin.flush()

            submit_done = False
            submit_timeout = 60
            submit_start = time.time()
            while time.time() - submit_start < submit_timeout:
                resp = read_mcp_response(proc, timeout_sec=5)
                if resp and resp.get("id") == 3 and "result" in resp:
                    submit_done = True
                    break
                time.sleep(0.5)

            if not submit_done:
                print(f"   ⚠️  doc2x 导出提交超时")
                proc.terminate()
                return None

            wait_msg = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "doc2x_convert_export_wait",
                    "arguments": {"uid": uid, "to": "md", "poll_interval": 5000},
                },
            }
            proc.stdin.write(json.dumps(wait_msg) + "\n")
            proc.stdin.flush()

            export_url = None
            start_time = time.time()
            interval = 2
            max_wait = min(timeout, 600)

            while time.time() - start_time < max_wait:
                resp = read_mcp_response(proc, timeout_sec=10)
                if resp and resp.get("id") == 4 and "result" in resp:
                    result = resp["result"]
                    if isinstance(result, dict):
                        content = result.get("content", [])
                        if content:
                            text = content[0].get("text", "")
                            if text:
                                try:
                                    data = json.loads(text)
                                    url = data.get("url")
                                    if url and data.get("status") == "success":
                                        export_url = url
                                        break
                                    if data.get("status") == "failed":
                                        print(f"   ⚠️  doc2x 导出失败")
                                        break
                                except json.JSONDecodeError:
                                    pass
                time.sleep(interval)
                interval = min(interval * 1.5, 20)

            proc.terminate()

            if export_url:
                print(f"   📥 正在从 URL 下载完整 markdown...")
                try:
                    req = urllib.request.Request(export_url)
                    with urllib.request.urlopen(req, timeout=120) as response:
                        zip_data = response.read()
                        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                            md_content = zf.read("output.md").decode("utf-8")
                            images_dir = Path(
                                "/Volumes/online/llamaindex/mddocs/images"
                            )
                            for name in zf.namelist():
                                if name.startswith("images/") and not name.endswith(
                                    "/"
                                ):
                                    img_data = zf.read(name)
                                    img_name = Path(name).name
                                    img_path = images_dir / img_name
                                    img_path.parent.mkdir(parents=True, exist_ok=True)
                                    img_path.write_bytes(img_data)

                            md_file_path = (
                                Path("/Volumes/online/llamaindex/mddocs")
                                / f"{Path(pdf_path).stem}.md"
                            )
                            meta = ConversionMetadata(
                                uid=uid,
                                is_truncated=False,
                            )
                            meta.save(md_file_path)

                            print(f"   ✅ doc2x 完整导出成功 ({len(md_content)} chars)")
                            return md_content
                except Exception as e:
                    print(f"   ⚠️  下载失败: {e}")

            return None

        except Exception as e:
            print(f"   ⚠️  doc2x 失败: {e}")
            if proc:
                proc.kill()
        return None

    def _convert_pdf_doc2x(
        self, pdf_path: str, api_key: str, timeout: int = None
    ) -> Optional[str]:
        """使用 doc2x MCP 转换 PDF（完整 markdown，无截断）

        Args:
            pdf_path: PDF 文件路径
            api_key: doc2x API Key
            timeout: 超时时间

        Returns:
            Markdown 内容，失败返回 None
        """
        env_file = Path(__file__).parent.parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value

        print(f"   ☁️  doc2x 完整解析...")
        md = self._doc2x_parse_and_export_full(pdf_path, api_key, timeout)
        if md:
            self._save_md_to_local(md, pdf_path)
            return md
        print(f"   ❌ doc2x 转换失败")
        return None

    def process_pdf(
        self,
        pdf_path: str,
        metadata: dict = None,
        force_ocr: bool = False,
        is_scanned: Optional[bool] = None,
        has_md_cache: Optional[bool] = None,
    ) -> List[LlamaDocument]:
        docs = []
        ext = Path(pdf_path).suffix.lower()

        md_file_path = (
            Path("/Volumes/online/llamaindex/mddocs") / f"{Path(pdf_path).stem}.md"
        )

        if force_ocr and md_file_path.exists():
            try:
                md_file_path.unlink()
                meta_path = md_file_path.with_suffix(".meta.json")
                meta_path.unlink(missing_ok=True)
            except Exception:
                pass

        # 优先使用 has_md_cache（如果前端已传递）
        if (
            has_md_cache is True
            and md_file_path.exists()
            and md_file_path.stat().st_size > 100
        ):
            meta = ConversionMetadata.load(md_file_path)
            if meta and not meta.is_truncated:
                print(f"   📄 使用已缓存的 MD（前端确认）: {md_file_path.name}")
                try:
                    md_content = md_file_path.read_text(encoding="utf-8")
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
                    return docs
                except Exception:
                    pass

        # fallback: 自动使用 MD 缓存（如果没有传递 has_md_cache）
        if (
            has_md_cache is None
            and not force_ocr
            and md_file_path.exists()
            and md_file_path.stat().st_size > 100
        ):
            meta = ConversionMetadata.load(md_file_path)
            if meta and not meta.is_truncated:
                print(f"   📄 使用已缓存的 MD: {md_file_path.name}")
                try:
                    md_content = md_file_path.read_text(encoding="utf-8")
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
                    return docs
                except Exception:
                    pass

        if is_scanned is None:
            is_scanned = self.is_scanned_pdf(pdf_path)

        if is_scanned:
            print(
                f"   🔍 {'用户强制' if force_ocr else '检测为'}扫描件，尝试 OCR 转换..."
            )
            md_content = self.convert_pdf_to_markdown(pdf_path)
            if md_content:
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
        from rag.ollama_utils import BatchEmbeddingHelper

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
                failed = []
                for node in processed_batch:
                    try:
                        node.embedding = self.embed_model.get_text_embedding(
                            node.get_content()
                        )
                    except Exception as ex:
                        print(f"      ⚠️  Embedding 失败: {ex}")
                        failed.append(node)
                for node in failed:
                    processed_batch.remove(node)

        # 保存所有节点
        try:
            lance_store = vector_store._get_lance_vector_store()
            saved, skipped, failed_ids = self._upsert_nodes(
                lance_store, processed_batch
            )
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
