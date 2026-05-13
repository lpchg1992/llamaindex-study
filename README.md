# LlamaIndex Study

基于 LlamaIndex 的现代化 RAG 应用，支持多知识库管理、多种数据源导入和高级检索策略。

## 特性

### 核心功能
- 📚 **多数据源** — Obsidian 笔记、Zotero 文献、通用文件
- 🗃️ **多知识库** — 独立向量存储，隔离管理
- ⚡ **并行处理** — 本地/远程 Ollama 自适应负载均衡
- 🔄 **增量同步** — 基于文件哈希检测变更
- 🧭 **统一导入编排** — CLI / API / 脚本共用 `ImportApplicationService`

### 检索策略
- 🔍 **混合搜索** — 向量检索 + LanceDB 原生全文搜索（FTS）
- 🔄 **Auto-Merging** — 检索时自动合并子节点为父节点
- 💭 **HyDE 查询** — 假设文档嵌入，提升检索质量
- 📝 **多查询转换** — 生成多个查询变体，减少遗漏
- 🎯 **Reranker 重排序** — Cross-Encoder 二次排序，提升精度
- 🔬 **Sub-Question 分解** — 复杂查询自动拆分为子问题
- 🤖 **ReAct Agent** — 多步推理 + 工具调用，自主决策检索策略
- 💬 **多模式聊天** — 5 种对话引擎（condense / context / simple 等），支持流式输出

### 质量保障
- ✅ **RAGAS 评估** — context_precision / recall / faithfulness / relevancy 自动评估
- 🔭 **LangFuse 可观测** — 全链路 Trace（检索→重排→生成）耗时 + Token 追踪
- 📊 **声明式 QueryPipeline** — DAG 检索链，可视化、可序列化、可热插拔

### 智能分块
- 🏗️ **层级分块** — 父子节点结构（默认），支持 Auto-Merging
- 🧩 **语义分块** — 基于 embedding 相似度的智能分块
- 🪟 **上下文窗口** — SentenceWindowNodeParser，精确检索场景
- 📝 **Markdown 分块** — 按标题层级结构切分

### 核心架构
- 🔧 **IngestionPipeline** — 声明式文档处理管道（参考文献检测 + 文本清洗 + 缓存）
- 🏷️ **元数据提取器** — Title/Summary/Question/Keyword 自动标注
- ✅ **RAG 评估** — Faithfulness / Relevancy / Correctness 内置评估

## 快速开始

### 环境要求
- Python >= 3.11
- [UV](https://github.com/astral-sh/uv) 包管理器
- 本地 [Ollama](https://ollama.ai/) (Embedding 服务)
- 硅基流动 API Key（可选，默认已集成）

### 1. 安装与配置

```bash
# 安装依赖
uv sync

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key

# 下载 embedding 模型
ollama pull bge-m3
```

### 2. 启动服务

```bash
# 启动 API 服务
uv run python -m api.main

# 或使用交互式 CLI
uv run llamaindex-study
```

服务地址：
- API: http://localhost:37241/docs
- WebSocket: ws://localhost:37241/ws/tasks

## 使用示例

### CLI 命令

```bash
# 知识库管理
uv run llamaindex-study kb list
uv run llamaindex-study kb create my_kb --name "我的知识库"

# 导入文档
uv run llamaindex-study ingest obsidian my_kb --folder-path 技术
uv run llamaindex-study ingest file my_kb ./docs.pdf
uv run llamaindex-study ingest zotero my_kb --collection-name "文献"
uv run llamaindex-study ingest batch my_kb ./docs ./notes

# topics 管理
uv run llamaindex-study kb topics my_kb --update
uv run llamaindex-study kb topics-local my_kb --update

# 检索问答
uv run llamaindex-study search my_kb "Python 异步编程"
uv run llamaindex-study query my_kb "如何优化代码性能"

# 自动路由（LLM 选择知识库）
uv run llamaindex-study search "猪饲料配方" --auto
uv run llamaindex-study query "如何优化代码性能" --auto

# 高级检索
uv run llamaindex-study query my_kb "..." --auto-merging  # Auto-Merging
uv run llamaindex-study query my_kb "..." --hyde         # HyDE 查询
uv run llamaindex-study query my_kb "..." --multi-query  # 多查询
uv run llamaindex-study query my_kb "..." --sub-question # Sub-Question 分解

# ReAct Agent（智能推理模式）
uv run llamaindex-study query "对比三个知识库的断奶仔猪营养建议" --agent

# 多模式聊天
uv run llamaindex-study chat my_kb --chat-mode condense_question
uv run llamaindex-study chat my_kb --chat-mode context --streaming

# RAGAS 评估
uv run llamaindex-study eval add-questions my_kb ./test_questions.json
uv run llamaindex-study eval run my_kb --metrics faithfulness,context_precision

# 任务管理
uv run llamaindex-study task list
uv run llamaindex-study task watch <task_id>
uv run llamaindex-study task cancel <task_id>

# 知识库一致性校验
uv run llamaindex-study kb consistency <kb_id>      # 校验单个 KB
uv run llamaindex-study kb consistency              # 校验所有 KB
uv run llamaindex-study kb consistency <kb_id> --repair  # 校验并修复
```


### Python API

```python
from kb_core.services import SearchService, KnowledgeBaseService

# 创建知识库
KnowledgeBaseService.create("my_kb", name="我的知识库")

# RAG 问答
result = SearchService.query("my_kb", "如何优化代码性能", top_k=5)
print(result)

# Sub-Question 分解
result = SearchService.query("my_kb", "复杂问题", use_sub_question=True)

# 自动路由（根据问题内容选择知识库）
from kb_core.services import QueryRouter
result = QueryRouter.query("Python 异步编程最佳实践")

# ReAct Agent（多步推理）
result = QueryRouter.query("对比分析三个知识库的建议", mode="agent")
```

### REST API 示例

```bash
# 获取知识库 topics
curl http://localhost:37241/kbs/HTE_history/topics

# 刷新知识库 topics
curl -X POST http://localhost:37241/kbs/HTE_history/topics/refresh \
  -H "Content-Type: application/json" \
  -d '{"has_new_docs": true}'

# ReAct Agent 问答
curl -X POST http://localhost:37241/query \
  -H "Content-Type: application/json" \
  -d '{"query": "对比分析断奶仔猪的营养方案", "route_mode": "agent"}'

# RAGAS 评估
curl -X POST http://localhost:37241/evaluation/run \
  -H "Content-Type: application/json" \
  -d '{"kb_id": "my_kb", "test_questions": [{"query": "...", "reference_answer": "..."}], "metrics": ["faithfulness", "context_precision"]}'
```

## 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `PERSIST_DIR` | `~/.llamaindex/storage` | 向量数据库持久化目录 |
| `LLAMAINDEX_STORAGE_BASE` | `~/.llamaindex/storage` | 知识库存储根目录 |
| `CHUNK_STRATEGY` | `hierarchical` | 分块策略：`hierarchical`/`sentence`/`semantic`/`markdown` |
| `CHUNK_SIZE` | `1024` | 分块大小 |
| `CHUNK_OVERLAP` | `100` | 分块重叠 |
| `HIERARCHICAL_CHUNK_SIZES` | `1024,512,256` | 层级分块各层大小 |
| `USE_AUTO_MERGING` | `false` | 启用 Auto-Merging |
| `USE_HYBRID_SEARCH` | `false` | 启用混合搜索（向量+关键词） |
| `MAX_CONCURRENT_TASKS` | `10` | 最大并发任务数 |
| `CORS_EXTRA_ORIGINS` | - | 额外的 CORS 来源（逗号分隔） |
| `LANGFUSE_SECRET_KEY` | - | LangFuse Secret Key（可选，配置后启用链路追踪） |
| `LANGFUSE_PUBLIC_KEY` | - | LangFuse Public Key |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | LangFuse 服务地址 |

> **模型配置**（LLM、Embedding、Reranker）通过 CLI/API 管理，存储在数据库中：
> ```bash
> uv run llamaindex-study vendor add ollama --api-base=http://localhost:11434
> uv run llamaindex-study model add ollama/bge-m3 --vendor ollama --type embedding
> ```
> 详见 `uv run llamaindex-study vendor add --help` 和 `uv run llamaindex-study model add --help`

详细配置请参考 [docs/API.md](docs/API.md#环境变量配置) 和 [.env.example](.env.example)。

## 文档

- [CLI 使用指南](docs/CLI.md) — 完整的命令行文档
- [API 文档](docs/API.md) — REST API 详细说明
- [架构设计](docs/ARCHITECTURE.md) — 系统架构与设计模式

## 项目结构

```
llamaindex-study/
├── api/                     # FastAPI 模块化服务
│   ├── main.py              # 应用入口
│   ├── schemas.py           # Pydantic 模型
│   ├── deps.py              # 共享依赖
│   └── routes/              # 路由模块
├── kb_cli/                   # CLI 命令实现
├── rag/                      # 核心库（RAG 组件）
│   ├── config.py             # 配置管理
│   ├── vector_store.py       # 向量数据库（LanceDB）
│   ├── query_engine.py       # 查询引擎（含 SubQuestion）
│   ├── chat_engine.py        # 对话引擎（5 种模式 + 流式输出）
│   ├── agent.py              # ReAct Agent（多步推理 + 工具调用）
│   ├── pipeline.py           # 声明式 QueryPipeline
│   ├── evaluation.py         # RAGAS 评估
│   ├── eval_storage.py       # 评估结果持久化
│   ├── callbacks.py          # LangFuse 可观测性回调
│   ├── ingestion.py          # IngestionPipeline
│   ├── response_synthesizer.py
│   ├── embedding_service.py  # Embedding 服务
│   └── reranker.py           # 重排序
├── kb_core/                  # 核心服务（业务逻辑）
│   ├── services/             # 服务层（拆分后）
│   │   ├── vector_store.py   # 向量存储服务
│   │   ├── knowledge_base.py # 知识库管理
│   │   ├── search.py         # 检索服务
│   │   ├── query_router.py   # 自动路由
│   │   ├── task.py           # 任务管理
│   │   ├── consistency.py    # 一致性校验
│   │   └── ...               # 其他服务
│   ├── database.py           # SQLite 数据库层
│   ├── task_scheduler.py     # 调度器（内嵌于 API）
│   ├── task_executor.py      # 任务执行器
│   ├── task_queue.py         # 任务队列
│   └── import_service.py     # 导入服务（统一入口）
├── kb_storage/               # 存储服务
├── kb_processing/            # 处理服务（Embedding 等）
│   └── parallel_embedding.py # 并行 Embedding 处理器
├── kb_analysis/              # 分析服务（topics、keywords）
├── kb_obsidian/              # Obsidian 集成
├── kb_zotero/                # Zotero 集成
├── scripts/                  # 工具脚本
├── webui/                    # Web UI (React)
└── docs/                     # 文档
    ├── API.md
    ├── CLI.md
    ├── ARCHITECTURE.md
    └── README.md
```
