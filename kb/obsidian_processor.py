"""
Obsidian 文档导入处理器

专门处理 Obsidian vault：
- Markdown 文件解析
- YAML frontmatter 提取
- Wiki 链接和标签处理
- 支持 PDF 附件（含 OCR）
- 目录结构和标签分类
"""

import ast
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from llama_index.core.schema import Document as LlamaDocument

from kb.document_processor import DocumentProcessor, DocumentProcessorConfig, ProcessingProgress


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
    """

    def __init__(
        self,
        vault_root: Optional[Path] = None,
        config: Optional[DocumentProcessorConfig] = None,
    ):
        """
        初始化 Obsidian 导入器

        Args:
            vault_root: Obsidian vault 根目录
            config: 文档处理器配置
        """
        self.vault_root = vault_root or Path.home() / "Documents" / "Obsidian Vault"
        self.processor = DocumentProcessor(config=config)

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
                                metadata["tags_list"] = tags_list if isinstance(tags_list, list) else [tags_list]
                            except:
                                metadata["tags_list"] = [v.strip() for v in value.strip("[]").split(",")]
                        elif "," in value:
                            metadata["tags_list"] = [v.strip() for v in value.split(",")]
                        else:
                            metadata["tags_list"] = [value]

            content = content[match.end():]

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
        content = re.sub(r"^\s*[-*]\s*\[\[[^\]]+\]\]\s*$", "", content, flags=re.MULTILINE)

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
            title = fm_metadata.get("title") or fm_metadata.get("alias") or file_path.stem

            return ObsidianNote(
                file_path=file_path,
                title=title,
                content=clean_content,
                tags=all_tags,
                frontmatter=fm_metadata,
                links=links,
            )

        except Exception as e:
            print(f"   ⚠️  解析失败: {file_path.name} - {e}")
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
    ) -> dict:
        """
        导入整个目录

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
        print(f"\n{'='*60}")
        print(f"📓 Obsidian: {directory.name}")
        print(f"{'='*60}")

        self.processor.set_embed_model(embed_model)
        node_parser = self.processor.node_parser

        # 保存排除模式并设置新的
        original_exclude = self.exclude_patterns.copy()
        if exclude_patterns is not None:
            self.exclude_patterns = exclude_patterns

        # 收集文件
        files = self.collect_files(directory, recursive=recursive)
        print(f"   找到 {len(files)} 个笔记")

        if not files:
            return {"files": 0, "nodes": 0, "failed": 0}

        if progress:
            progress.total_items = len(files)
            if not progress.started_at:
                progress.started_at = time.time()

        processed_set = set(progress.processed_items) if progress else set()

        stats = {"files": 0, "nodes": 0, "failed": 0}

        for i, file_path in enumerate(files):
            if str(file_path) in processed_set:
                continue

            if i % 10 == 0:
                elapsed = time.time() - (progress.started_at if progress else time.time())
                print(f"\n   进度: {i+1}/{len(files)} ({100*(i+1)//len(files)}%)")
                print(f"   节点: {stats['nodes']}, 耗时: {elapsed:.0f}s")

            if on_progress:
                on_progress(i + 1, len(files), file_path.name)

            # 解析笔记
            note = self.parse_note(file_path)
            if not note:
                stats["failed"] += 1
                continue

            # 获取相对路径
            try:
                rel_path = str(file_path.relative_to(self.vault_root))
            except ValueError:
                rel_path = str(file_path)

            # 准备元数据
            metadata = {
                "source": "obsidian",
                "file_path": str(file_path),
                "relative_path": rel_path,
                "title": note.title,
                "tags": ", ".join(note.tags),
                "obsidian_tags": list(note.tags),
                **note.frontmatter,
            }

            # 创建文档
            doc = LlamaDocument(
                text=note.content,
                metadata=metadata,
                id_=f"obsidian_{rel_path}",
            )

            # 解析为节点
            nodes = node_parser.get_nodes_from_documents([doc])

            # 保存
            saved = self.processor.save_nodes(vector_store, nodes, progress)
            stats["nodes"] += saved
            stats["files"] += 1

            if progress:
                progress.processed_items.append(str(file_path))
                progress.save(Path.home() / ".llamaindex" / "obsidian_progress.json")

        # 处理 PDF 附件
        pdf_stats = self.import_pdf_attachments(directory, vector_store, embed_model, progress)
        stats["nodes"] += pdf_stats.get("nodes", 0)

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
        print(f"\n   🔍 扫描 PDF 附件...")

        pdf_files = list(directory.rglob("*.pdf"))
        if not pdf_files:
            return {"files": 0, "nodes": 0}

        print(f"   找到 {len(pdf_files)} 个 PDF")

        self.processor.set_embed_model(embed_model)

        stats = {"files": 0, "nodes": 0}

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
                for doc in docs:
                    nodes = node_parser.get_nodes_from_documents([doc])
                    saved = self.processor.save_nodes(vector_store, nodes, progress)
                    stats["nodes"] += saved
                    stats["files"] += 1

                if progress:
                    progress.processed_items.append(str(pdf_path))

        return stats
