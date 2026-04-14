#!/usr/bin/env python3
"""
快速健康检查工具

检查本地和远程 Ollama 服务的可用性和性能
"""

import asyncio
import time
import httpx
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.config import get_settings


async def check_endpoint(name: str, url: str) -> dict:
    """检查单个端点"""
    result = {
        "name": name,
        "url": url,
        "available": False,
        "latency_ms": 0,
        "error": None,
    }
    
    try:
        # HTTP 检查
        start = time.time()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/api/tags", timeout=5)
        result["latency_ms"] = (time.time() - start) * 1000
        
        if response.status_code == 200:
            result["available"] = True
            data = response.json()
            models = [m["name"] for m in data.get("models", [])]
            result["models"] = models
    except httpx.TimeoutException:
        result["error"] = "连接超时"
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def check_embedding(name: str, url: str, model: str = "bge-m3") -> dict:
    """测试 embedding 性能"""
    result = {
        "name": name,
        "embedding_latency_ms": 0,
        "embedding_working": False,
        "error": None,
    }
    
    try:
        from llama_index.embeddings.ollama import OllamaEmbedding
        
        embed = OllamaEmbedding(model_name=model, base_url=url)
        
        # 预热
        await embed.aget_text_embedding("预热")
        
        # 测试
        start = time.time()
        await embed.aget_text_embedding("猪营养配方设计原理")
        result["embedding_latency_ms"] = (time.time() - start) * 1000
        result["embedding_working"] = True
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def main():
    print("=" * 60)
    print("Ollama 健康检查")
    print("=" * 60)

    settings = get_settings()
    endpoints = settings.get_ollama_endpoints()
    if not endpoints:
        endpoints = [("本地", settings.ollama_base_url)]
    
    # 检查所有端点
    results = []
    for name, url in endpoints:
        print(f"\n检查 {name} ({url})...")
        
        # HTTP 检查
        http_result = await check_endpoint(name, url)
        
        if http_result["available"]:
            print(f"  ✅ HTTP 可用 (延迟: {http_result['latency_ms']:.0f}ms)")
            print(f"  📦 模型: {', '.join(http_result.get('models', []))}")
            
            # Embedding 测试
            emb_result = await check_embedding(name, url, model=settings.ollama_embed_model)
            if emb_result["embedding_working"]:
                print(f"  ✅ Embedding 正常 (延迟: {emb_result['embedding_latency_ms']:.0f}ms)")
                results.append((name, emb_result["embedding_latency_ms"]))
            else:
                print(f"  ❌ Embedding 失败: {emb_result['error']}")
        else:
            print(f"  ❌ HTTP 不可用: {http_result['error']}")
    
    # 推荐
    if results:
        print("\n" + "=" * 60)
        print("推荐配置")
        print("=" * 60)
        results.sort(key=lambda x: x[1])
        
        for i, (name, latency) in enumerate(results, 1):
            print(f"  {i}. {name} (延迟: {latency:.0f}ms)")
        
        fastest = results[0][0]
        print(f"\n💡 建议优先使用: {fastest}")


if __name__ == "__main__":
    asyncio.run(main())
