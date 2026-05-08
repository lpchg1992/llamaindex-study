"""
Obsidian 文档导入处理器

专门处理 Obsidian vault：
- Markdown 文件解析
- YAML frontmatter 提取
- Wiki 链接和标签处理
- 支持 PDF 附件（含 OCR）
- 目录结构和标签分类
- 增量同步（基于 documents 表）
"""

import ast
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Any

from llama_index.core.schema import Document as LlamaDocument

from kb_processing.document_processor import (
    DocumentProcessor,
    DocumentProcessorConfig,
    ProcessingProgress,
)
from kb_core.document_chunk_service import get_document_chunk_service
from rag.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ObsidianNote:
    """Obsidian 笔记"""

    file_path: Path
    title: str
    content: str
    tags: Set[str] = field(default_factory=set)
    frontmatter: dict = field(default_factory=dict)
    links: List[str] = field(default_factory=list)
    backlinks: List[str] = field(default_factory=list)


class ObsidianImporter:
    """
    Obsidian 笔记导入器

    功能：
    - 解析 Obsidian markdown 格式
    - 提取 YAML frontmatter
    - 清理 wiki 链接和标签
    - 处理 PDF 附件（含 OCR）
    - 目录结构和标签分类
    - 增量同步（基于 documents 表）
    """

    def __init__(
        self,
        vault_root: Optional[Path] = None,
        config: Optional[DocumentProcessorConfig] = None,
        kb_id: Optional[str] = None,
        persist_dir: Optional[Path] = None,
        vector_store: Optional[Any] = None,
    ):
        """
        初始化 Obsidian 导入器

        Args:
            vault_root: Obsidian vault 根目录
            config: 文档处理器配置
            kb_id: 知识库 ID（用于去重管理）
            persist_dir: 持久化目录（用于去重管理）
            vector_store: 向量存储（用于去重管理）
        """
        self.vault_root = vault_root or Path.home() / "Documents" / "Obsidian Vault"
        self.processor = DocumentProcessor(config=config)
        self.kb_id = kb_id
        self.persist_dir = persist_dir
        self.vector_store = vector_store

        # 默认排除模式
        self.exclude_patterns = [
            "*/image/*",
            "*/_resources/*",
            "*/.obsidian/*",
            "*/.trash/*",
        ]

    @staticmethod
    def extract_tags(content: str) -> Set[str]:
        """
        提取内容中的所有标签

        支持：#tag, #tag/subtag, #中文标签
        """
        pattern = r"#([a-zA-Z0-9_\u4e00-\u9fff/]+)"
        return set(re.findall(pattern, content))

    @staticmethod
    def extract_links(content: str) -> List[str]:
        """提取 wiki 链接 [[link]]"""
        # 匹配 [[link]] 和 [[link|display]]
        pattern = r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]"
        return re.findall(pattern, content)

    def extract_frontmatter(self, content: str) -> tuple[str, dict]:
        """
        提取 YAML frontmatter

        Returns:
            (正文内容, frontmatter字典)
        """
        metadata = {}

        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if match:
            fm_text = match.group(1)
            for line in fm_text.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    metadata[key] = value

                    # 解析 tags 字段
                    if key.lower() in ("tags", "tag"):
                        if value.startswith("["):
                            try:
                                tags_list = ast.literal_eval(value)
                                metadata["tags_list"] = (
                                    tags_list
                                    if isinstance(tags_list, list)
                                    else [tags_list]
                                )
                            except (ValueError, SyntaxError):
                                metadata["tags_list"] = [
                                    v.strip() for v in value.strip("[]").split(",")
                                ]
                        elif "," in value:
                            metadata["tags_list"] = [
                                v.strip() for v in value.split(",")
                            ]
                        else:
                            metadata["tags_list"] = [value]

            content = content[match.end() :]

        return content, metadata

    @staticmethod
    def clean_content(content: str, remove_tags: bool = True) -> str:
        """
        清理 Obsidian markdown 内容
        """
        # 1. 移除 YAML frontmatter
        content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
        content = re.sub(r"^---\n.*?\n---", "", content, flags=re.DOTALL)

        # 2. 移除 wiki 图片/链接 ![[filename]]
        content = re.sub(r"!\[\[[^\]]+\]\]", "", content)

        # 3. 替换 wiki 内部链接为纯文本
        content = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", content)

        # 4. 移除标签
        if remove_tags:
            content = re.sub(r"#[a-zA-Z0-9_\u4e00-\u9fff/]+", "", content)

        # 5. 移除 HTML 注释
        content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

        # 6. 移除嵌入标签
        content = re.sub(r"\{\{(video|audio|image):[^}]+\}\}", "", content)

        # 7. 清理多余空行
        content = re.sub(r"\n{3,}", "\n\n", content)

        # 8. 移除空链接行
        content = re.sub(
            r"^\s*[-*]\s*\[\[[^\]]+\]\]\s*$", "", content, flags=re.MULTILINE
        )

        return content.strip()

    def parse_note(self, file_path: Path) -> Optional[ObsidianNote]:
        """
        解析单个笔记文件
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_content = f.read()

            # 跳过空文件
            if not raw_content.strip():
                return None

            # 提取 frontmatter
            content, fm_metadata = self.extract_frontmatter(raw_content)

            # 提取标签
            content_tags = self.extract_tags(content)
            fm_tags = set(fm_metadata.get("tags_list", []))
            all_tags = content_tags.union(fm_tags)

            # 提取链接
            links = self.extract_links(content)

            # 清理内容
            clean_content = self.clean_content(content, remove_tags=True)

            # 跳过空内容
            if len(clean_content.strip()) < 50:
                return None

            # 获取标题
            title = (
                fm_metadata.get("title") or fm_metadata.get("alias") or file_path.stem
            )

            return ObsidianNote(
                file_path=file_path,
                title=title,
                content=clean_content,
                tags=all_tags,
                frontmatter=fm_metadata,
                links=links,
            )

        except Exception as e:
            logger.warning(f"解析失败: {file_path.name} - {e}")
            return None

    def collect_files(
        self,
        directory: Optional[Path] = None,
        recursive: bool = True,
    ) -> List[Path]:
        """
        收集 vault 中的 markdown 文件
        """
        vault_dir = directory or self.vault_root

        if not vault_dir.exists():
            return []

        files = []
        for f in (vault_dir.rglob if recursive else vault_dir.glob)("*.md"):
            # 检查是否应该排除
            should_exclude = False
            for pattern in self.exclude_patterns:
                pattern_parts = pattern.split("*")
                if all(part in str(f) for part in pattern_parts):
                    should_exclude = True
                    break

            if not should_exclude:
                # 跳过过大的文件
                if f.stat().st_size < 100 * 1024:  # 100KB
                    files.append(f)

        return files

    def import_directory(
        self,
        directory: Path,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
        rebuild: bool = False,
        on_progress: Optional[callable] = None,
        exclude_patterns: Optional[List[str]] = None,
        recursive: bool = True,
        force_delete: bool = True,
    ) -> dict:
        """
        导入整个目录（支持增量同步）

        Args:
            directory: 目录路径
            vector_store: 向量存储
            embed_model: embedding 模型
            progress: 进度记录
            rebuild: 是否重建
            on_progress: 进度回调
            exclude_patterns: 排除的文件模式（可选）
            recursive: 是否递归（可选）

        Returns:
            导入统计
        """
        logger.info(f"开始导入 Obsidian: {directory.name}")

        self.processor.set_embed_model(embed_model)
        node_parser = self.processor.node_parser

        # 保存排除模式并设置新的
        original_exclude = self.exclude_patterns.copy()
        if exclude_patterns is not None:
            self.exclude_patterns = exclude_patterns

        # 收集文件
        files = self.collect_files(directory, recursive=recursive)
        logger.info(f"找到 {len(files)} 个笔记")

        if not files:
            return {"files": 0, "nodes": 0, "failed": 0}

        # ========== 增量同步：基于 Document 表检测变更 ==========
        from kb_core.database import init_document_db

        doc_db = init_document_db()
        if not files:
            return {"files": 0, "nodes": 0, "failed": 0}

        if progress:
            progress.total_items = len(files)
            if not progress.started_at:
                progress.started_at = time.time()

        # 兼容旧的 progress.processed_items 方式
        processed_set = set(progress.processed_items) if progress else set()

        stats = {"files": 0, "nodes": 0, "failed": 0, "processed_sources": []}

        for i, file_path in enumerate(files):
            try:
                rel_path = str(file_path.relative_to(self.vault_root))
            except ValueError:
                rel_path = str(file_path)

            if not rebuild:
                existing = doc_db.get_by_source_path(self.kb_id, str(file_path))
                if existing:
                    current_hash = self.processor.compute_file_hash(str(file_path))
                    if existing.get("file_hash") == current_hash:
                        continue

            if str(file_path) in processed_set:
                continue

            if i % 10 == 0:
                elapsed = time.time() - (
                    progress.started_at if progress else time.time()
                )
                logger.info(
                    f"进度: {i + 1}/{len(files)} ({100 * (i + 1) // len(files)}%), "
                    f"节点: {stats['nodes']}, 耗时: {elapsed:.0f}s"
                )

            if on_progress:
                on_progress(i + 1, len(files), file_path.name)

            # 解析笔记
            note = self.parse_note(file_path)
            if not note:
                stats["failed"] += 1
                continue

            # 获取相对路径（已在上面获取）
            # rel_path 已在 try-except 块中获取

            # 准备元数据（确保所有值都是标准类型）
            def clean_value(v):
                """清理值为标准类型"""
                if v is None:
                    return ""
                if isinstance(v, (str, int, float, bool)):
                    return v
                if isinstance(v, list):
                    return [clean_value(x) for x in v]
                return str(v)

            metadata = {
                "source": "obsidian",
                "file_path": str(file_path),
                "relative_path": rel_path,
                "title": str(note.title) if note.title else "",
                "tags": ", ".join(str(t) for t in note.tags),
                "tag_list": ",".join(str(t) for t in note.tags),  # 用逗号分隔的字符串
            }
            # 添加 frontmatter（转换为标准类型）
            for key, value in note.frontmatter.items():
                metadata[str(key)] = clean_value(value)

            # ========== 修复：统一 Doc ID 生成方式 ==========
            # 使用 rel_path 作为 ID，与 ingest_vdb.py 保持一致
            doc_id = rel_path

            # 创建文档
            doc = LlamaDocument(
                text=note.content,
                metadata=metadata,
                id_=doc_id,
            )

            # 解析为节点
            nodes = node_parser.get_nodes_from_documents([doc])

            # 清理节点 metadata，确保所有值都是标准类型且长度合适
            def clean_node_metadata(node):
                """清理节点 metadata"""
                MAX_STR_LENGTH = 500  # 最大字符串长度

                for key in list(node.metadata.keys()):
                    value = node.metadata[key]
                    if value is None:
                        node.metadata[key] = ""
                    elif isinstance(value, str):
                        # 截断过长的字符串
                        if len(value) > MAX_STR_LENGTH:
                            node.metadata[key] = value[:MAX_STR_LENGTH] + "..."
                    elif not isinstance(value, (str, int, float, bool)):
                        try:
                            node.metadata[key] = str(value)[:MAX_STR_LENGTH]
                        except Exception:
                            del node.metadata[key]
                return node

            nodes = [clean_node_metadata(n) for n in nodes]

            texts = [node.get_content() for node in nodes]
            failed_node_ids = []
            for i, node in enumerate(nodes):
                try:
                    ep = embed_model._get_best_endpoint()
                    ep_name, embedding, error = embed_model._get_embedding_with_retry(texts[i], ep)
                    text_len = len(texts[i])
                    if error:
                        logger.warning(
                            f"[{file_path.name}] Embedding failed (endpoint={ep_name}, node={node.node_id[:8]}, text_len={text_len}): {error}"
                        )
                        failed_node_ids.append(node.node_id)
                    elif all(v == 0.0 for v in embedding):
                        logger.warning(
                            f"[{file_path.name}] Embedding returned zero vector (endpoint={ep_name}, node={node.node_id[:8]}, text_len={text_len})"
                        )
                        failed_node_ids.append(node.node_id)
                    else:
                        node.embedding = embedding
                except Exception as emb_err:
                    logger.error(
                        f"[{file_path.name}] Embedding exception (node={node.node_id[:8]}): {type(emb_err).__name__}: {emb_err}"
                    )
                    failed_node_ids.append(node.node_id)

            doc_chunk_service = get_document_chunk_service(self.kb_id)
            file_hash = self.processor.compute_file_hash(str(file_path))
            result = doc_chunk_service.create_document(
                source_file=file_path.name,
                source_path=str(file_path),
                file_hash=file_hash,
                nodes=nodes,
                file_size=file_path.stat().st_size,
                doc_id=doc_id,
                failed_node_ids=failed_node_ids if failed_node_ids else None,
            )
            if not result:
                logger.warning(f"SQLite 文档记录创建失败: {file_path}")
                continue

            try:
                lance_store = vector_store._get_lance_vector_store()
                success_count, written_ids, _, emb_failed_ids = self.processor._upsert_nodes(lance_store, nodes)
                if written_ids:
                    doc_chunk_service.mark_chunks_success(written_ids)
                if emb_failed_ids:
                    doc_chunk_service.mark_chunks_failed(emb_failed_ids, error="embedding unavailable (missing or zero vector)")
            except Exception as write_ex:
                logger.warning(f"LanceDB 写入失败（SQLite 已保存）: {file_path}, 错误: {write_ex}")
                node_ids = [n.node_id for n in nodes]
                doc_chunk_service.mark_chunks_failed(node_ids, error=f"LanceDB write failed: {write_ex}")
                continue

            stats["nodes"] += success_count
            stats["files"] += 1
            stats["processed_sources"].append(str(file_path))

            if progress:
                progress.processed_items.append(str(file_path))
                progress.save(
                    Path.home() / ".llamaindex" / "obsidian_progress.json"
                )

        # 处理 PDF 附件
        pdf_stats = self.import_pdf_attachments(
            directory, vector_store, embed_model, progress
        )
        stats["nodes"] += pdf_stats.get("nodes", 0)
        stats["processed_sources"].extend(pdf_stats.get("processed_sources", []))

        # 恢复原来的排除模式
        self.exclude_patterns = original_exclude

        return stats

    def import_pdf_attachments(
        self,
        directory: Path,
        vector_store,
        embed_model,
        progress: ProcessingProgress = None,
    ) -> dict:
        """
        导入目录中的 PDF 附件
        """
        logger.debug("扫描 PDF 附件...")

        pdf_files = list(directory.rglob("*.pdf"))
        if not pdf_files:
            return {"files": 0, "nodes": 0}

        logger.debug(f"找到 {len(pdf_files)} 个 PDF")

        self.processor.set_embed_model(embed_model)

        stats = {"files": 0, "nodes": 0, "processed_sources": []}
        doc_chunk_service = get_document_chunk_service(self.kb_id)

        for pdf_path in pdf_files:
            if progress and str(pdf_path) in progress.processed_items:
                continue

            # 获取相对路径作为元数据
            try:
                rel_path = str(pdf_path.relative_to(self.vault_root))
            except ValueError:
                rel_path = str(pdf_path)

            metadata = {
                "source": "obsidian_pdf",
                "file_path": str(pdf_path),
                "relative_path": rel_path,
                "parent_vault": str(self.vault_root),
            }

            docs = self.processor.process_pdf(str(pdf_path), metadata=metadata)

            if docs:
                node_parser = self.processor.node_parser
                all_file_nodes = []
                for doc in docs:
                    nodes = node_parser.get_nodes_from_documents([doc])
                    all_file_nodes.extend(nodes)

                if all_file_nodes:
                    texts = [node.get_content() for node in all_file_nodes]
                    failed_node_ids = []
                    for i, node in enumerate(all_file_nodes):
                        try:
                            ep = embed_model._get_best_endpoint()
                            ep_name, embedding, error = embed_model._get_embedding_with_retry(texts[i], ep)
                            if error:
                                failed_node_ids.append(node.node_id)
                            elif all(v == 0.0 for v in embedding):
                                failed_node_ids.append(node.node_id)
                            else:
                                node.embedding = embedding
                        except Exception as emb_err:
                            logger.error(f"PDF Embedding exception: {emb_err}")
                            failed_node_ids.append(node.node_id)

                    file_hash = self.processor.compute_file_hash(str(pdf_path))
                    result = doc_chunk_service.create_document(
                        source_file=pdf_path.name,
                        source_path=str(pdf_path),
                        file_hash=file_hash,
                        nodes=all_file_nodes,
                        file_size=pdf_path.stat().st_size,
                        doc_id=f"obsidian_pdf_{pdf_path.stat().st_ino}",
                        failed_node_ids=failed_node_ids if failed_node_ids else None,
                    )
                    if not result:
                        logger.warning(f"SQLite 文档记录创建失败: {pdf_path}")
                        continue

                    try:
                        lance_store = vector_store._get_lance_vector_store()
                        success_count, written_ids, _, emb_failed_ids = self.processor._upsert_nodes(lance_store, all_file_nodes)
                        if written_ids:
                            doc_chunk_service.mark_chunks_success(written_ids)
                        if emb_failed_ids:
                            doc_chunk_service.mark_chunks_failed(emb_failed_ids, error="embedding unavailable (missing or zero vector)")
                    except Exception as e:
                        logger.warning(f"LanceDB 写入失败: {pdf_path}, 错误: {e}")
                        node_ids = [n.node_id for n in all_file_nodes]
                        doc_chunk_service.mark_chunks_failed(node_ids, error=f"LanceDB write failed: {e}")
                        continue

                    stats["nodes"] += success_count
                    stats["files"] += 1
                    stats["processed_sources"].append(str(pdf_path))
                    if progress:
                        progress.processed_items.append(str(pdf_path))

        return stats
