"""
文档加载模块

提供智能文档加载和切分功能，支持最佳实践配置：
- 基于 Token 的切分（而非字符）
- Markdown 标题层级感知
- 语义切分（Semantic Chunking）
- 多格式支持（PDF、Word、Markdown、Text）
"""

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Union

from llama_index.core.schema import Document as LlamaDocument


class ChunkStrategy(str, Enum):
    """切分策略"""
    SENTENCE = "sentence"          # 按句子切分（通用）
    SEMANTIC = "semantic"          # 语义切分（最佳）
    MARKDOWN = "markdown"          # 按 Markdown 标题切分
    PAGE = "page"                 # 按页面切分（PDF）


@dataclass
class ChunkConfig:
    """切分配置"""
    
    # Token 相关配置（LlamaIndex 默认按 token 计）
    chunk_size: int = 512                  # 每个块的目标大小（tokens）
    chunk_overlap: int = 50                 # 相邻块重叠（tokens）
    
    # 策略
    strategy: ChunkStrategy = ChunkStrategy.SEMANTIC
    
    # Markdown 专用
    header_path_separator: str = " > "     # 标题路径分隔符
    
    # 语义切分专用
    similarity_threshold: float = 0.5      # 相似度阈值
    percentile_threshold: Optional[float] = None  # 百分位阈值（替代）
    
    # 保留关系
    include_metadata: bool = True           # 包含元数据
    include_prev_next_rel: bool = True     # 包含前后关系
    
    def to_sentence_splitter(self):
        """转换为 SentenceSplitter"""
        from llama_index.core.node_parser import SentenceSplitter
        return SentenceSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            include_metadata=self.include_metadata,
            include_prev_next_rel=self.include_prev_next_rel,
        )
    
    def to_markdown_parser(self):
        """转换为 MarkdownNodeParser"""
        from llama_index.core.node_parser import MarkdownNodeParser
        return MarkdownNodeParser.from_defaults(
            include_metadata=self.include_metadata,
            include_prev_next_rel=self.include_prev_next_rel,
            header_path_separator=self.header_path_separator,
        )
    
    def to_semantic_chunker(self, embed_model):
        """转换为 SemanticChunker（必须传入真实的 embedding 模型）"""
        if embed_model is None:
            raise ValueError(
                "SemanticChunker 需要传入真实的 embed_model，不支持为 None。"
                "请使用 SmartDocumentProcessor(embed_model=your_embed_model) 传入 embedding 模型。"
            )
        try:
            from llama_index.packs.node_parser_semantic_chunking.base import SemanticChunker
        except ImportError:
            raise ImportError(
                "SemanticChunker 不可用（需要 llama-index-packs-node-parser-semantic-chunking）。"
                "请安装: pip install llama-index-packs-node-parser-semantic-chunking"
            )

        return SemanticChunker(
            embed_model=embed_model,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            similarity_threshold=self.similarity_threshold,
            percentile_threshold=self.percentile_threshold,
            include_metadata=self.include_metadata,
            include_prev_next_rel=self.include_prev_next_rel,
        )


class DocumentReader:
    """
    文档加载器
    
    使用 SimpleDirectoryReader 加载目录中的文档文件。
    支持 .txt, .md, .pdf, .docx 等常见格式。
    """

    def __init__(
        self,
        input_dir: Union[str, Path],
        recursive: bool = True,
        required_exts: Optional[List[str]] = None,
        filename_as_id: bool = True,
    ):
        """
        初始化文档加载器
        
        Args:
            input_dir: 文档目录路径
            recursive: 是否递归搜索子目录
            required_exts: 限定加载的文件扩展名
            filename_as_id: 是否使用文件名作为文档 ID
        """
        self.input_dir = Path(input_dir)
        self.recursive = recursive
        self.required_exts = required_exts
        self.filename_as_id = filename_as_id

    def load(self) -> List[LlamaDocument]:
        """
        加载目录中的所有文档
        
        Returns:
            List[Document]: 文档列表
        """
        if not self.input_dir.exists():
            raise FileNotFoundError(f"文档目录不存在: {self.input_dir}")

        from llama_index.core import SimpleDirectoryReader

        reader = SimpleDirectoryReader(
            input_dir=str(self.input_dir),
            recursive=self.recursive,
            required_exts=self.required_exts,
            filename_as_id=self.filename_as_id,
            exclude=[
                "*/image/*",
                "*/images/*",
                "*/.obsidian/*",
                "*/_resources/*",
            ],
        )

        documents = reader.load_data()
        return documents

    @staticmethod
    def load_file(file_path: Union[str, Path]) -> List[LlamaDocument]:
        """加载单个文件"""
        from llama_index.core import SimpleDirectoryReader

        reader = SimpleDirectoryReader(
            input_files=[str(file_path)],
            filename_as_id=True,
        )
        return reader.load_data()


class SmartDocumentProcessor:
    """
    智能文档处理器
    
    支持多种切分策略，符合 RAG 最佳实践：
    - SEMANTIC: 语义切分（基于嵌入相似度）
    - MARKDOWN: 按 Markdown 标题层级切分
    - SENTENCE: 按句子切分（通用）
    - PAGE: 按页面切分（PDF 专用）
    
    推荐配置:
    - chunk_size: 512 tokens（保持上下文精简）
    - chunk_overlap: 50 tokens（保留跨块连续性）
    - strategy: SEMANTIC（最佳效果）
    """

    # 默认配置 - 最佳实践
    DEFAULT_CONFIG = ChunkConfig(
        chunk_size=512,        # 512 tokens ≈ 400-600 中文词
        chunk_overlap=50,      # 10% 重叠
        strategy=ChunkStrategy.SEMANTIC,
    )

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        strategy: Union[str, ChunkStrategy] = ChunkStrategy.SEMANTIC,
        **kwargs,
    ):
        """
        初始化文档处理器
        
        Args:
            chunk_size: 每个块的目标大小（tokens）
            chunk_overlap: 相邻块重叠大小（tokens）
            strategy: 切分策略
                - "semantic": 语义切分（推荐，最佳）
                - "markdown": 按标题切分（适合 Markdown）
                - "sentence": 按句子切分（通用）
                - "page": 按页面切分（PDF）
        """
        if isinstance(strategy, str):
            strategy = ChunkStrategy(strategy)
        
        self.config = ChunkConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=strategy,
            **kwargs,
        )

    def get_node_parser(self, embed_model=None):
        """获取节点解析器"""
        strategy = self.config.strategy

        if strategy == ChunkStrategy.SEMANTIC:
            if embed_model is None:
                raise ValueError(
                    "SEMANTIC 策略需要传入 embed_model，请使用 "
                    "SmartDocumentProcessor(...).process_documents(documents, embed_model=your_embed_model)"
                )
            return self.config.to_semantic_chunker(embed_model=embed_model)
        elif strategy == ChunkStrategy.MARKDOWN:
            return self.config.to_markdown_parser()
        elif strategy == ChunkStrategy.PAGE:
            # Page 策略使用默认的 SentenceSplitter
            return self.config.to_sentence_splitter()
        else:
            return self.config.to_sentence_splitter()

    def process_documents(
        self,
        documents: List[LlamaDocument],
        show_progress: bool = True,
        embed_model=None,
    ) -> List:
        """
        处理文档列表，将其切分为节点

        Args:
            documents: 文档列表
            show_progress: 是否显示进度
            embed_model: embedding 模型（用于语义切分）

        Returns:
            List[Node]: 切分后的节点列表
        """
        node_parser = self.get_node_parser(embed_model=embed_model)
        nodes = node_parser.get_nodes_from_documents(documents, show_progress=show_progress)
        return nodes

    def process_file(
        self,
        file_path: Union[str, Path],
        show_progress: bool = True,
        embed_model=None,
    ) -> List:
        """
        处理单个文件

        Args:
            file_path: 文件路径
            show_progress: 是否显示进度
            embed_model: embedding 模型（用于语义切分）

        Returns:
            List[Node]: 切分后的节点列表
        """
        docs = DocumentReader.load_file(file_path)
        return self.process_documents(docs, show_progress=show_progress, embed_model=embed_model)

    @staticmethod
    def process_pdf(
        file_path: Union[str, Path],
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        strategy: Union[str, ChunkStrategy] = ChunkStrategy.SENTENCE,
    ) -> List[LlamaDocument]:
        """
        专门处理 PDF 文件
        
        Args:
            file_path: PDF 文件路径
            chunk_size: 切分大小
            chunk_overlap: 重叠大小
            strategy: 切分策略
        
        Returns:
            List[Document]: 文档列表
        """
        from llama_index.readers.file import PDFReader

        reader = PDFReader(
            return_full_document=False,  # 按页
        )

        documents = reader.load_data(file=Path(file_path))
        return documents

    @staticmethod
    def get_pdf_info(file_path: Union[str, Path]) -> dict:
        """获取 PDF 文件信息"""
        import pypdf

        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            info = {
                "num_pages": len(reader.pages),
                "metadata": reader.metadata if hasattr(reader, 'metadata') else {},
            }

            file_path = Path(file_path)
            if file_path.exists():
                info["file_size"] = file_path.stat().st_size
                info["file_size_mb"] = round(info["file_size"] / (1024 * 1024), 2)

            return info

    @classmethod
    def for_markdown(cls, chunk_size: int = 512, chunk_overlap: int = 50) -> "SmartDocumentProcessor":
        """
        创建适合 Markdown 的处理器
        
        Args:
            chunk_size: 切分大小
            chunk_overlap: 重叠大小
        
        Returns:
            SmartDocumentProcessor 实例
        """
        return cls(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=ChunkStrategy.MARKDOWN,
        )

    @classmethod
    def for_semantic(cls, chunk_size: int = 512, chunk_overlap: int = 50, **kwargs) -> "SmartDocumentProcessor":
        """
        创建语义切分处理器（推荐）
        
        Args:
            chunk_size: 切分大小
            chunk_overlap: 重叠大小
            **kwargs: 其他配置
        
        Returns:
            SmartDocumentProcessor 实例
        """
        return cls(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=ChunkStrategy.SEMANTIC,
            **kwargs,
        )

    @classmethod
    def for_pdf(cls, chunk_size: int = 512, chunk_overlap: int = 50) -> "SmartDocumentProcessor":
        """
        创建适合 PDF 的处理器
        
        Args:
            chunk_size: 切分大小
            chunk_overlap: 重叠大小
        
        Returns:
            SmartDocumentProcessor 实例
        """
        return cls(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            strategy=ChunkStrategy.SENTENCE,  # PDF 用句子切分
        )


def load_and_split(
    input_dir: Union[str, Path],
    chunk_size: int = 512,
    chunk_overlap: int = 50,
    strategy: Union[str, ChunkStrategy] = ChunkStrategy.SEMANTIC,
    required_exts: Optional[List[str]] = None,
    show_progress: bool = True,
) -> tuple:
    """
    便捷函数：加载文档并切分
    
    Args:
        input_dir: 文档目录
        chunk_size: 切分大小（tokens）
        chunk_overlap: 重叠大小（tokens）
        strategy: 切分策略
        required_exts: 文件扩展名过滤
        show_progress: 显示进度
    
    Returns:
        tuple: (documents, nodes)
    """
    reader = DocumentReader(
        input_dir=input_dir,
        required_exts=required_exts,
    )
    documents = reader.load()

    processor = SmartDocumentProcessor(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=strategy,
    )
    nodes = processor.process_documents(documents, show_progress=show_progress)

    return documents, nodes


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量
    
    粗略估算：中文约 1.5-2 tokens/字，英文约 1.3-1.5 tokens/词
    
    Args:
        text: 文本
    
    Returns:
        估算的 token 数量
    """
    # 中文
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    # 英文词
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    # 其他
    other = len(text) - chinese_chars - english_words
    
    # 估算：中文 1.5 tokens/字，英文 1.5 tokens/词，其他 1 token/字符
    return int(chinese_chars * 1.5 + english_words * 1.5 + other)


def estimate_tokens_by_length(char_count: int) -> int:
    """
    根据字符数估算 token 数量
    
    Args:
        char_count: 字符数
    
    Returns:
        估算的 token 数量
    """
    # 粗略估算：1 token ≈ 1.5 字符
    return int(char_count / 1.5)
