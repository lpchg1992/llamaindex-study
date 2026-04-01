#!/usr/bin/env python3
"""
LlamaIndex Study - 交互式查询入口

功能：
1. 加载 data/ 目录下的所有文档
2. 构建向量索引
3. 进入交互式查询循环

使用方法：
    uv run python main.py
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from llamaindex_study.config import get_settings
from llamaindex_study.reader import DocumentReader
from llamaindex_study.index_builder import IndexBuilder
from llamaindex_study.query_engine import QueryEngineWrapper


def print_welcome() -> None:
    """打印欢迎信息和命令提示"""
    print("\n" + "=" * 60)
    print("🤖 LlamaIndex Study - 交互式查询系统")
    print("=" * 60)
    print("\n命令提示：")
    print("  - 输入问题并按回车进行查询")
    print("  - 输入 'stream' 切换流式/普通模式")
    print("  - 输入 'reload' 重新加载索引")
    print("  - 输入 'quit' 或 'exit' 退出程序")
    print("=" * 60 + "\n")


def load_documents(data_dir: Path) -> list:
    """
    加载文档
    
    Args:
        data_dir: 文档目录路径
    
    Returns:
        List[Document]: 文档列表
    """
    print(f"📂 正在加载文档: {data_dir}")
    
    reader = DocumentReader(
        input_dir=data_dir,
        required_exts=[".txt", ".md"],  # 只加载文本和 Markdown 文件
    )
    
    documents = reader.load()
    print(f"✅ 成功加载 {len(documents)} 个文档\n")
    return documents


def main() -> None:
    """主函数"""
    # 初始化配置
    settings = get_settings()
    print(f"🔧 使用配置: {settings}")
    print(f"   LLM: SiliconFlow ({settings.siliconflow_model})")
    print(f"   Embedding: Ollama ({settings.ollama_embed_model})")
    
    # 文档目录
    data_dir = Path(__file__).parent / "data"
    
    # 持久化目录
    persist_dir = Path(settings.persist_dir)
    
    # 加载文档
    documents = load_documents(data_dir)
    
    # 构建索引
    print("🔨 正在构建向量索引...")
    builder = IndexBuilder(persist_dir=persist_dir)
    
    # 尝试从持久化存储加载索引
    index = builder.load()
    
    # 如果没有已保存的索引，则构建新索引
    if index is None:
        print("📦 没有找到已有索引，正在从头构建...")
        index = builder.build_from_documents(documents)
        
        # 保存索引
        builder.save(index)
    
    # 创建查询引擎
    query_engine = QueryEngineWrapper(
        index=index,
        top_k=settings.top_k,
    )
    
    # 打印欢迎信息
    print_welcome()
    
    # 流式模式标志
    stream_mode = False
    
    # 交互式查询循环
    while True:
        try:
            # 获取用户输入
            user_input = input("💬 你: ").strip()
            
            # 处理命令
            if user_input.lower() in ["quit", "exit", "q"]:
                print("\n👋 再见！感谢使用 LlamaIndex Study。")
                break
            
            elif user_input.lower() == "stream":
                stream_mode = not stream_mode
                status = "开启" if stream_mode else "关闭"
                print(f"🔄 流式输出已{status}\n")
                continue
            
            elif user_input.lower() == "reload":
                print("\n🔄 正在重新加载文档和索引...")
                documents = load_documents(data_dir)
                index = builder.build_from_documents(documents)
                query_engine = QueryEngineWrapper(
                    index=index,
                    top_k=settings.top_k,
                )
                print("✅ 索引已重新加载\n")
                continue
            
            elif not user_input:
                continue
            
            # 执行查询
            print("\n🤖 AI: ", end="", flush=True)
            
            if stream_mode:
                query_engine.query(user_input, stream=True)
            else:
                response = query_engine.query(user_input, stream=False)
                print(response)
            
            print()  # 空行
            
        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {e}\n")


if __name__ == "__main__":
    main()
