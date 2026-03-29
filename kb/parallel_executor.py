"""
并行文件夹导入器

本地处理奇数文件夹，远程处理偶数文件夹，同时进行
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

from llamaindex_study.logger import get_logger
from llamaindex_study.ollama_utils import create_ollama_embedding, BatchEmbeddingHelper

logger = get_logger(__name__)


# 端点配置
LOCAL_ENDPOINT = {
    "name": "本地",
    "url": "http://localhost:11434",
    "model": "bge-m3",
}

REMOTE_ENDPOINT = {
    "name": "远程 3080",
    "url": "http://192.168.31.169:11434",
    "model": "bge-m3",
}


class ParallelFolderImporter:
    """
    并行文件夹导入器
    
    本地处理文件夹 A 列表，远程处理文件夹 B 列表，同时进行。
    """
    
    def __init__(
        self,
        vault_path: Path,
        kb_id: str,
        folders: List[str],
        local_endpoint: Optional[Dict[str, str]] = None,
        remote_endpoint: Optional[Dict[str, str]] = None,
    ):
        self.vault_path = vault_path
        self.kb_id = kb_id
        self.folders = folders
        
        self.local_endpoint = local_endpoint or LOCAL_ENDPOINT
        self.remote_endpoint = remote_endpoint or REMOTE_ENDPOINT
        
        # 通用排除模式
        self.exclude_patterns = [
            "*/image/*", "*/_resources/*", "*/.obsidian/*",
            "*/.trash/*", "*/Z_Copilot/*", "*/copilot-custom-prompts/*",
            "*/Z模版/*", "*/Z_网页/*", "*/English/*",
        ]
        
        self.results: List[Dict[str, Any]] = []
    
    def _get_folder_stats(self, folder: str) -> int:
        """获取文件夹中的文件数量"""
        folder_path = self.vault_path / folder
        if not folder_path.exists():
            return 0
        
        count = 0
        for md_file in folder_path.rglob("*.md"):
            rel_path = str(md_file.relative_to(self.vault_path))
            excluded = any(pattern.replace("*", "") in rel_path for pattern in self.exclude_patterns)
            if not excluded:
                count += 1
        return count
    
    async def _import_folder(
        self,
        folder: str,
        endpoint: Dict[str, str],
        vs,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """使用指定端点导入文件夹"""
        from kb.obsidian_processor import ObsidianImporter
        from llama_index.core import Settings
        
        start_time = time.time()
        folder_path = self.vault_path / folder
        
        if not folder_path.exists():
            return {
                "folder": folder,
                "endpoint": endpoint["name"],
                "files": 0,
                "nodes": 0,
                "failed": 0,
                "elapsed": 0,
                "error": "文件夹不存在",
            }
        
        # 创建 embedder
        embed_model = create_ollama_embedding(
            model=endpoint["model"],
            base_url=endpoint["url"],
        )
        Settings.embed_model = embed_model
        
        # 创建 importer
        importer = ObsidianImporter(vault_root=self.vault_path)
        importer.exclude_patterns = self.exclude_patterns
        
        try:
            if progress_callback:
                progress_callback(f"[{endpoint['name']}] 导入: {folder}")
            
            stats = importer.import_directory(
                directory=folder_path,
                vector_store=vs,
                embed_model=embed_model,
                progress=None,
                exclude_patterns=importer.exclude_patterns,
                recursive=True,
            )
            
            elapsed = time.time() - start_time
            
            return {
                "folder": folder,
                "endpoint": endpoint["name"],
                "files": stats.get("files", 0),
                "nodes": stats.get("nodes", 0),
                "failed": stats.get("failed", 0),
                "elapsed": elapsed,
                "error": None,
            }
            
        except Exception as e:
            logger.error(f"导入失败 {folder}: {e}")
            return {
                "folder": folder,
                "endpoint": endpoint["name"],
                "files": 0,
                "nodes": 0,
                "failed": -1,
                "elapsed": time.time() - start_time,
                "error": str(e),
            }
    
    async def run(
        self,
        vs,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> List[Dict[str, Any]]:
        """并发导入所有文件夹"""
        logger.info(f"开始并行导入 {len(self.folders)} 个文件夹")
        
        # 计算每个文件夹的文件数量
        folder_stats = [(f, self._get_folder_stats(f)) for f in self.folders]
        folder_stats.sort(key=lambda x: x[1], reverse=True)
        
        # 智能分配：交替使用本地和远程
        local_folders = []
        remote_folders = []
        
        for i, (folder, count) in enumerate(folder_stats):
            if count == 0:
                continue
            if i % 2 == 0:
                local_folders.append(folder)
            else:
                remote_folders.append(folder)
        
        if len(remote_folders) == 0 and len(local_folders) > 0:
            remote_folders.append(local_folders.pop(0))
        
        logger.info(f"本地处理 {len(local_folders)} 个文件夹: {local_folders}")
        logger.info(f"远程处理 {len(remote_folders)} 个文件夹")
        
        if progress_callback:
            total_local = sum(s for f, s in folder_stats if f in local_folders)
            total_remote = sum(s for f, s in folder_stats if f in remote_folders)
            progress_callback(f"本地: {len(local_folders)} 文件夹 ({total_local} 文件), 远程: {len(remote_folders)} 文件夹 ({total_remote} 文件)")
        
        # 创建所有任务
        tasks = []
        for folder in local_folders:
            tasks.append(self._import_folder(folder, self.local_endpoint, vs, progress_callback))
        
        for folder in remote_folders:
            tasks.append(self._import_folder(folder, self.remote_endpoint, vs, progress_callback))
        
        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"任务异常: {result}")
                self.results.append({
                    "folder": "unknown",
                    "endpoint": "error",
                    "files": 0,
                    "nodes": 0,
                    "failed": -1,
                    "elapsed": 0,
                    "error": str(result),
                })
            else:
                self.results.append(result)
                logger.info(
                    f"完成: {result['folder']} ({result['endpoint']}), "
                    f"{result['files']} 文件, {result['nodes']} 节点, {result['elapsed']:.1f}s"
                )
        
        return self.results


async def parallel_import_kb(
    kb_id: str,
    folders: List[str],
    vault_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    并行导入知识库
    
    Args:
        kb_id: 知识库 ID
        folders: 文件夹列表
        vault_path: Vault 路径
        progress_callback: 进度回调
        
    Returns:
        导入结果列表
    """
    from kb.registry import get_storage_root
    from llamaindex_study.vector_store import LanceDBVectorStore
    
    if vault_path is None:
        vault_path = Path.home() / "Documents" / "Obsidian Vault"
    
    persist_dir = get_storage_root() / kb_id
    vs = LanceDBVectorStore(persist_dir=persist_dir, table_name=kb_id)
    
    importer = ParallelFolderImporter(
        vault_path=vault_path,
        kb_id=kb_id,
        folders=folders,
    )
    
    return await importer.run(vs, progress_callback)
