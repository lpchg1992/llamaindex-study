# LlamaIndex 学习项目

一个基于 LlamaIndex v0.10+ 的现代化 RAG（检索增强生成）学习项目。

## 架构说明

```
用户查询
    ↓
Embedding（本地 Ollama / bge-m3）
    ↓
向量检索（向量数据库）
    ↓
LLM（硅基流动 SiliconFlow / OpenAI 兼容 API）
    ↓
生成回答
```

- **Embedding**：本地运行（Ollama + bge-m3），支持 100+ 语言包括中英文，**中文能力强**
- **LLM**：硅基流动（OpenAI 兼容格式，DeepSeek-V3/R1 原生中英文支持）
- **向量数据库**：支持 LanceDB（默认）、Chroma、Qdrant

## 环境要求

- Python >= 3.11
- Poetry（Python 包管理器）
- Ollama（本地 Embedding 服务）
- 硅基流动 API Key（注册送 14 元额度：https://www.siliconflow.com）

## 快速开始

### 1. 安装 Ollama（Embedding 服务）

```bash
# 安装 Ollama
brew install ollama

# 启动 Ollama（后台运行）
ollama serve

# 下载 embedding 模型（支持中英文，推荐 bge-m3）
ollama pull bge-m3
```

### 2. 克隆并安装项目

```bash
cd ~/文档/GitHub/llamaindex-study

# 安装依赖
poetry install

# 复制并编辑环境变量
cp .env.example .env
# 编辑 .env，填入 SILICONFLOW_API_KEY
```

### 3. 配置 .env

```env
SILICONFLOW_API_KEY=你的密钥
SILICONFLOW_MODEL=deepseek-ai/DeepSeek-V3
OLLAMA_EMBED_MODEL=bge-m3
PERSIST_DIR=./storage
```

### 4. 运行

```bash
# 基本示例
poetry run python example.py

# 交互式查询（命令行对话）
poetry run python main.py
```

### 5. 添加自己的文档

将文档放入 `data/` 目录，支持格式：
- `.txt` 纯文本 ✅
- `.md` Markdown ✅
- `.pdf` PDF 文档 ✅（自动按页加载）
- `.docx` Word 文档 ✅

文档会自动切分为合适大小的块（基于 Token，智能策略），便于向量检索。

**最佳实践切分参数：**

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| `chunk_size` | 256-512 tokens | 每块目标大小 |
| `chunk_overlap` | 50-100 tokens | 块之间重叠（10-20%） |
| `strategy` | SEMANTIC | 语义切分（推荐） |

### 6. 增量同步

支持基于文件哈希的增量同步机制：

```bash
# 查看变更（不执行）
poetry run python -m kb.ingest_vdb --show-changes

# 增量同步（自动检测新增/更新/删除）
poetry run python -m kb.ingest_vdb

# 强制重建（清空后重新导入）
poetry run python -m kb.ingest_vdb --rebuild

# 只同步指定知识库
poetry run python -m kb.ingest_vdb --kb tech_tools

# 不同步删除的文件
poetry run python -m kb.ingest_vdb --no-delete
```

**同步状态文件：** `.sync_state.json`（记录每个文件的 hash 和同步状态）

## 向量数据库支持

本项目支持多种向量数据库，可根据需求选择：

### LanceDB（默认，推荐）

```bash
# 查看知识库状态
poetry run python -m kb.ingest_vdb --stats

# 导入知识库到 LanceDB
poetry run python -m kb.ingest_vdb --kb tech_tools

# 重建索引
poetry run python -m kb.ingest_vdb --kb tech_tools --rebuild
```

### Chroma（轻量级）

```bash
poetry run python -m kb.ingest_vdb --engine chroma --kb tech_tools
```

### Qdrant（生产级，需要本地或云端部署）

```bash
poetry run python -m kb.ingest_vdb --engine qdrant --kb tech_tools
```

## 项目结构

```
llamaindex-study/
├── README.md
├── pyproject.toml
├── .env.example          # 环境变量模板
├── .env                  # 实际配置（不提交）
├── data/
│   ├── sample.txt        # 示例文档
│   └── sample.pdf        # 示例 PDF
├── src/llamaindex_study/
│   ├── __init__.py
│   ├── config.py         # 配置管理
│   ├── reader.py         # 文档加载 + 智能切分
│   ├── index_builder.py  # 索引构建（Ollama embedding）
│   ├── query_engine.py   # 查询引擎（SiliconFlow LLM）
│   └── vector_store.py   # 向量数据库管理
├── kb/
│   ├── __init__.py
│   ├── registry.py       # 知识库注册表（支持目录+标签分类）
│   ├── obsidian_reader.py # Obsidian 文档解析 + 分类器
│   ├── zotero_reader.py  # Zotero 文献库读取器
│   └── ingest_vdb.py      # 向量数据库导入脚本
├── examples/
│   ├── document_processing_example.py  # 文档处理示例
│   ├── vector_store_example.py         # 向量数据库示例
│   ├── obsidian_classifier_example.py  # 文档分类示例
│   └── zotero_example.py              # Zotero 文献库示例
├── main.py               # 交互式查询
└── example.py            # 示例脚本
```

## Obsidian 文档分类

支持基于**目录路径**和**标签**的混合分类：

```python
from kb.obsidian_reader import ObsidianReader, ObsidianClassifier

# 提取文档标签
tags = ObsidianReader.extract_tags(content)
# {'猪营养', '饲料', '蛋白质'}

# 分类文档
classifier = ObsidianClassifier()
matches = classifier.classify(document)
# ['swine_nutrition', 'tech_tools']
```

### 分类规则

| 匹配方式 | 说明 |
|---------|------|
| 目录路径 | 文档在指定目录树下 |
| 标签匹配 | 文档包含 `#对应标签` |
| 混合匹配 | 同时满足则归入多个知识库 |

### 支持的标签格式

```markdown
#猪营养 #饲料配方
#python #AI工具
#学术 #论文笔记
```

也支持 frontmatter 中的 tags 字段：

```yaml
---
tags: [学术, 论文, 研究]
---
```

## Zotero 文献库集成

支持从 Zotero 直接读取文献、标注和笔记：

```python
from kb.zotero_reader import create_zotero_reader

# 创建读取器
reader = create_zotero_reader()

# 获取统计信息
stats = reader.get_statistics()
print(f"文献总数: {stats['total_items']}")
print(f"标注总数: {stats['total_annotations']}")

# 按收藏夹加载文献
items = reader.load_items(collection_id=8)  # 营养饲料理论

# 转换为 LlamaIndex Document
docs = reader.load_as_documents(collection_id=8)

# 搜索文献
items = reader.load_items(search_query="猪营养")
```

### Zotero 数据统计

| 项目 | 数量 |
|------|------|
| 文献总数 | 3111 |
| 标注总数 | 791 |
| 笔记总数 | 102 |
| 收藏夹数 | 342 |

## 硅基流动模型推荐

| 模型 | 特点 | 适用场景 |
|------|------|----------|
| `deepseek-ai/DeepSeek-V3` | 通用强模型，低成本 | 日常问答、文档总结 |
| `deepseek-ai/DeepSeek-R1` | 推理能力强，思维链 | 复杂推理、分析任务 |
| `Qwen/Qwen2.5-7B-Instruct` | 开源稳定 | 通用对话 |

## LlamaIndex v0.10+ API

本项目使用 LlamaIndex 最新 API：

```python
# ✅ 新版 API (v0.10+)
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.openai import OpenAI  # SiliconFlow 兼容
from llama_index.embeddings.ollama import OllamaEmbedding

# ❌ 旧版 API (已废弃)
from llama_index import GPTVectorStoreIndex  # 不要使用！
```
