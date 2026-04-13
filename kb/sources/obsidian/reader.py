"""
Obsidian 文档读取器

专门处理 Obsidian vault 中的 markdown 文件：
- 移除 YAML frontmatter
- 清理 wiki 链接 ![[]] 和 [[]]
- 提取标签 #tag 并用于分类
- 提取元数据
"""

import re
from pathlib import Path
from typing import List, Optional, Set, Union

from llama_index.core.schema import Document as LlamaDocument

from llamaindex_study.logger import get_logger
from kb.registry import KnowledgeBase

logger = get_logger(__name__)


class ObsidianReader:
    """
    Obsidian 文档加载器

    继承 SimpleDirectoryReader 的功能，专门针对 Obsidian 格式进行优化。
    支持基于目录路径和标签的分类。
    """

    def __init__(
        self,
        input_dir: Union[str, Path],
        vault_root: Optional[Path] = None,
        recursive: bool = True,
        exclude_patterns: Optional[List[str]] = None,
    ):
        """
        初始化 Obsidian 文档加载器

        Args:
            input_dir: 文档目录路径
            vault_root: Obsidian vault 根目录（用于计算相对路径）
            recursive: 是否递归搜索子目录
            exclude_patterns: 排除的文件模式（如 */image/*, */_resources/*）
        """
        self.input_dir = Path(input_dir)
        self.vault_root = vault_root or Path.home() / "Documents" / "Obsidian Vault"
        self.recursive = recursive
        self.exclude_patterns = exclude_patterns or [
            "*/image/*",
            "*/_resources/*",
            "*/.obsidian/*",
        ]

    def _should_exclude(self, path: Path) -> bool:
        """检查是否应该排除该文件"""
        path_str = str(path)
        for pattern in self.exclude_patterns:
            # 简单的通配符匹配
            pattern_parts = pattern.split("*")
            if all(part in path_str for part in pattern_parts):
                return True
        return False

    @staticmethod
    def extract_tags(content: str) -> Set[str]:
        """
        提取内容中的所有 Obsidian 标签

        支持的格式：
        - #tag
        - #tag/subtag
        - #tag1 #tag2

        Args:
            content: 文档内容

        Returns:
            标签集合
        """
        # 匹配 #标签（支持中文、英文、数字、下划线、斜杠）
        pattern = r"#([a-zA-Z0-9_\u4e00-\u9fff/]+)"
        tags = re.findall(pattern, content)
        return set(tags)

    @staticmethod
    def clean_content(content: str, remove_tags: bool = True) -> str:
        """
        清理 Obsidian markdown 内容

        Args:
            content: 原始文件内容
            remove_tags: 是否移除标签（True=清理，False=保留）

        Returns:
            清理后的内容
        """
        # 1. 移除 YAML frontmatter ---...---
        content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)
        content = re.sub(
            r"^---\n.*?\n---", "", content, flags=re.DOTALL
        )  # 单行 frontmatter

        # 2. 移除 wiki 图片/链接 ![[filename]]
        content = re.sub(r"!\[\[[^\]]+\]\]", "", content)

        # 3. 移除 wiki 内部链接 [[link|display]] 和 [[link]]
        content = re.sub(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]", r"\1", content)

        # 4. 移除 Obsidian 标签 #tag（如果需要）
        if remove_tags:
            content = re.sub(r"#[a-zA-Z0-9_\u4e00-\u9fff/]+", "", content)

        # 5. 移除 HTML 注释 <!-- comment -->
        content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

        # 6. 移除音频/视频嵌入 {{video}}, {{audio}} 等
        content = re.sub(r"\{\{(video|audio|image):[^}]+\}\}", "", content)

        # 7. 清理多余空行（保留最多2个连续空行）
        content = re.sub(r"\n{3,}", "\n\n", content)

        # 8. 移除只包含链接的残留行（如 - [[link]]）
        content = re.sub(
            r"^\s*[-*]\s*\[\[[^\]]+\]\]\s*$", "", content, flags=re.MULTILINE
        )

        # 9. 清理行首行尾空白
        content = content.strip()

        return content

    def _clean_obsidian_content(self, content: str, file_path: Path) -> str:
        """兼容旧接口"""
        return self.clean_content(content, remove_tags=True)

    def _get_relative_path(self, file_path: Path) -> str:
        """获取相对于 vault 的路径"""
        try:
            return str(file_path.relative_to(self.vault_root))
        except ValueError:
            return str(file_path)

    def _extract_frontmatter(self, content: str) -> tuple[str, dict]:
        """
        提取 YAML frontmatter 元数据

        Returns:
            (正文内容, frontmatter字典)
        """
        metadata = {}

        match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
        if match:
            fm_text = match.group(1)
            # 简单的 key: value 解析
            for line in fm_text.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    metadata[key] = value

                    # 解析 tags 字段（支持数组和逗号分隔）
                    if key.lower() in ("tags", "tag"):
                        # 处理数组格式: [tag1, tag2]
                        if value.startswith("["):
                            import ast

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
                        # 处理逗号分隔: tag1, tag2
                        elif "," in value:
                            metadata["tags_list"] = [
                                v.strip() for v in value.split(",")
                            ]
                        # 单个标签
                        else:
                            metadata["tags_list"] = [value]

            content = content[match.end() :]

        return content, metadata

    # 最大文件大小（超过此大小跳过，单位字节）
    MAX_FILE_SIZE = 100_000  # 100KB

    def load(self) -> List[LlamaDocument]:
        """
        加载目录中的所有 Obsidian 文档

        Returns:
            LlamaDocument 列表
        """
        if not self.input_dir.exists():
            raise FileNotFoundError(f"文档目录不存在: {self.input_dir}")

        documents = []
        md_files = []

        # 收集所有 md 文件
        if self.recursive:
            for path in self.input_dir.rglob("*.md"):
                md_files.append(path)
        else:
            for path in self.input_dir.glob("*.md"):
                md_files.append(path)

        for file_path in md_files:
            if self._should_exclude(file_path):
                continue

            try:
                # 跳过过大的文件（可能是 PDF 引用笔记等）
                file_size = file_path.stat().st_size
                if file_size > self.MAX_FILE_SIZE:
                    print(
                        f"      ⏭️  跳过过大文件 ({file_size / 1024:.0f}KB): {file_path.name}"
                    )
                    continue

                with open(file_path, "r", encoding="utf-8") as f:
                    raw_content = f.read()

                # 提取 frontmatter
                content, fm_metadata = self._extract_frontmatter(raw_content)

                # 提取标签
                content_tags = self.extract_tags(content)
                # 合并 frontmatter 中的标签
                fm_tags = set(fm_metadata.get("tags_list", []))
                all_tags = content_tags.union(fm_tags)

                # 清理内容（移除标签）
                clean_content = self.clean_content(content, remove_tags=True)

                # 跳过空内容或过短内容
                if len(clean_content.strip()) < 50:
                    continue

                # 获取相对路径
                rel_path = self._get_relative_path(file_path)

                # 创建文档
                doc = LlamaDocument(
                    text=clean_content,
                    metadata={
                        "source": "obsidian",
                        "file_path": str(file_path),
                        "relative_path": rel_path,
                        "file_name": file_path.name,
                        "obsidian_tags": list(all_tags),  # 保存提取的标签
                        **fm_metadata,
                    },
                )
                documents.append(doc)

            except Exception as e:
                print(f"⚠️ 读取失败 {file_path}: {e}")
                continue

        return documents

    @staticmethod
    def load_files(
        file_paths: List[Path],
        vault_root: Optional[Path] = None,
    ) -> List[LlamaDocument]:
        """
        加载指定的文件列表

        Args:
            file_paths: 文件路径列表
            vault_root: Obsidian vault 根目录

        Returns:
            LlamaDocument 列表
        """
        reader = ObsidianReader(
            input_dir=file_paths[0].parent if file_paths else Path("."),
            vault_root=vault_root,
            recursive=False,
        )

        documents = []
        for file_path in file_paths:
            if not file_path.exists():
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    raw_content = f.read()

                content, fm_metadata = reader._extract_frontmatter(raw_content)
                clean_content = reader.clean_content(content, remove_tags=True)

                if len(clean_content.strip()) < 50:
                    continue

                rel_path = reader._get_relative_path(file_path)

                doc = LlamaDocument(
                    text=clean_content,
                    metadata={
                        "source": "obsidian",
                        "file_path": str(file_path),
                        "relative_path": rel_path,
                        "file_name": file_path.name,
                        **fm_metadata,
                    },
                )
                documents.append(doc)

            except Exception as e:
                print(f"⚠️ 读取失败 {file_path}: {e}")
                continue

        return documents


class ObsidianClassifier:
    """
    Obsidian 文档分类器

    根据目录路径和标签对文档进行分类。
    支持多知识库分类，一个文档可以属于多个知识库。
    """

    def __init__(
        self,
        knowledge_bases: Optional[List["KnowledgeBase"]] = None,
    ):
        """
        初始化分类器

        Args:
            knowledge_bases: 知识库列表
        """
        from kb.registry import KnowledgeBaseRegistry

        self.registry = KnowledgeBaseRegistry()
        self.kbs = knowledge_bases or self.registry.list_all()

    def match_by_path(self, relative_path: str) -> List[str]:
        """
        根据文件路径匹配知识库

        Args:
            relative_path: 相对于 vault 根目录的路径

        Returns:
            匹配的知识库 ID 列表
        """
        matched = []
        for kb in self.kbs:
            for source_path in kb.source_paths:
                if source_path in relative_path:
                    if kb.id not in matched:
                        matched.append(kb.id)
                    break
        return matched

    def match_by_tags(self, tags: List[str]) -> List[str]:
        """
        根据标签匹配知识库

        Args:
            tags: 文档的标签列表

        Returns:
            匹配的知识库 ID 列表
        """
        matched = []
        for kb in self.kbs:
            for source_tag in kb.source_tags:
                for doc_tag in tags:
                    # 精确匹配或包含匹配
                    if (
                        source_tag == doc_tag
                        or source_tag in doc_tag
                        or doc_tag in source_tag
                    ):
                        if kb.id not in matched:
                            matched.append(kb.id)
                            break
        return matched

    def classify(self, document: LlamaDocument) -> List[str]:
        """
        对文档进行分类

        匹配规则：
        1. 先按目录路径匹配
        2. 再按标签匹配
        3. 两者结合，合并结果

        Args:
            document: LlamaDocument 文档

        Returns:
            匹配的知识库 ID 列表
        """
        # 获取元数据
        relative_path = document.metadata.get("relative_path", "")
        obsidian_tags = document.metadata.get("obsidian_tags", [])
        tags_list = document.metadata.get("tags_list", [])

        # 合并所有标签
        all_tags = set(obsidian_tags) if isinstance(obsidian_tags, list) else set()
        all_tags.update(tags_list) if isinstance(tags_list, list) else all_tags.add(
            tags_list
        )

        # 按路径匹配
        path_matches = self.match_by_path(relative_path)

        # 按标签匹配
        tag_matches = self.match_by_tags(list(all_tags))

        # 合并结果（去重，保持顺序）
        all_matches = []
        for kb_id in path_matches + tag_matches:
            if kb_id not in all_matches:
                all_matches.append(kb_id)

        return all_matches

    def classify_documents(
        self,
        documents: List[LlamaDocument],
    ) -> dict:
        """
        对文档列表进行分类

        Args:
            documents: 文档列表

        Returns:
            dict: {知识库ID: [文档列表]}
        """
        result = {kb.id: [] for kb in self.kbs}
        unclassified = []

        for doc in documents:
            matches = self.classify(doc)
            if matches:
                for kb_id in matches:
                    result[kb_id].append(doc)
            else:
                unclassified.append(doc)

        # 添加未分类文档
        result["_unclassified"] = unclassified

        return result
