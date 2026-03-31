# CLI 使用文档

LlamaIndex Study 提供功能丰富的命令行工具 `llamaindex-study`，支持知识库管理、文档导入、检索问答等操作。

## 快速开始

### 启动交互模式

```bash
uv run llamaindex-study
```

进入交互模式后，**默认使用自动路由**，系统会根据问题内容自动选择最相关的知识库。

支持以下命令：

| 命令 | 说明 |
|------|------|
| `<问题>` | 自动选择知识库进行 RAG 问答 |
| `/search <kb_id> <query>` | 指定知识库检索 |
| `/query <kb_id> <question>` | 指定知识库问答 |
| `/list` | 显示知识库列表 |
| `/exclude <kb1,kb2,...>` | 设置排除的知识库 |
| `/excludes` | 查看当前排除设置 |
| `/auto` | 切换自动/手动选择知识库 |
| `stream` | 切换流式/普通输出模式 |
| `quit` / `exit` / `q` | 退出程序 |

示例：

```
💬 你: Python 异步编程的最好实践是什么？

📊 查询了: tech_tools
💬 回答：
Python 异步编程的最佳实践包括...

💬 你: /search tech_tools Python async

🔍 在知识库 [tech_tools] 中检索...
📊 找到 5 条结果：

  [1] (score: 0.92)
      Python asyncio 使用指南...

  [2] (score: 0.85)
      异步编程实战技巧...

💬 你: /exclude tech_tools,academic

🚫 已设置排除知识库: tech_tools, academic

💬 你: 猪的营养需要哪些？
📊 查询了: swine_nutrition, zotero_nutrition
```

### 查看帮助

```bash
# 查看全局帮助
uv run llamaindex-study --help

# 查看子命令帮助
uv run llamaindex-study kb --help
uv run llamaindex-study ingest --help
uv run llamaindex-study task --help
```

---

## 命令总览

```
llamaindex-study <command> [subcommand] [options]

命令分类:
  chat                          交互式问答
  kb                            知识库管理
  search                        向量检索
  query                         RAG 问答
  ingest                        文档导入
  obsidian                      Obsidian 辅助
  zotero                        Zotero 辅助
  task                          任务管理
  category                      分类规则
  admin                         管理命令
  config                        配置管理
```

### 交互式问答 (chat)

```bash
uv run llamaindex-study chat
```

启动交互式问答界面，支持自然语言查询。

---

## 知识库管理 (kb)

### 列出知识库

```bash
uv run llamaindex-study kb list
```

输出示例：

```
id                   name                 status    row_count  description
-------------------- -------------------- --------- ---------- ----------------
tech_tools           技术工具             indexed   1248      技术文档知识库
swine_nutrition      猪营养学             indexed   3421      猪营养研究资料
zotero_nutrition     Zotero营养学         indexed   892       Zotero导入文献
```

### 查看知识库详情

```bash
uv run llamaindex-study kb show <kb_id>
```

示例：

```bash
uv run llamaindex-study kb show tech_tools
```

### 创建知识库

```bash
uv run llamaindex-study kb create <kb_id> --name <名称> [--description <描述>]
```

示例：

```bash
uv run llamaindex-study kb create my_kb --name "我的知识库" --description "个人文档"
```

### 删除知识库

```bash
uv run llamaindex-study kb delete <kb_id> --yes
```

⚠️ 需要 `--yes` 确认删除。

### 重建知识库

```bash
uv run llamaindex-study kb rebuild <kb_id> [--wait]
```

- 不加 `--wait`：异步提交任务，立即返回 task_id
- 加 `--wait`：同步执行，等待完成

### 知识库主题分析

分析知识库内容，使用 LLM 提取专业主题词，用于自动路由。

#### 方式一：CLI 命令（推荐）

```bash
# 使用远程模型（DeepSeek）分析
uv run llamaindex-study kb topics <kb_id> [--all] [--update]

# 使用本地模型分析（一次性处理已有知识库，省成本）
uv run llamaindex-study kb topics-local <kb_id> [--all] [--update]
```

| 参数 | 说明 |
|------|------|
| `kb_id` | 知识库 ID（省略则需配合 `--all`） |
| `--all` | 分析所有知识库 |
| `--update` | 更新到数据库 |

示例：

```bash
# 分析单个KB（使用远程模型，导入时自动调用）
uv run llamaindex-study kb topics swine_nutrition

# 分析所有KB并更新（使用远程模型）
uv run llamaindex-study kb topics --all --update

# 使用本地模型分析（适合处理已有大量KB）
uv run llamaindex-study kb topics-local swine_nutrition --update
uv run llamaindex-study kb topics-local --all --update
```

#### 方式二：独立脚本

```bash
# 使用远程模型
uv run python kb/scripts/analyze_kb_topics.py <kb_id> [--update]

# 使用本地模型
uv run python kb/scripts/analyze_kb_topics_local.py <kb_id> [--update]
```

> **区别**：`kb topics` / `kb topics-local` 是集成在 CLI 中的命令；脚本方式适合调试或自定义场景。

---

## 检索查询

### 向量检索

```bash
uv run llamaindex-study search [<kb_id>] "<查询词>" [-k <top_k>] [--auto] [--exclude <kb1,kb2>] [--auto-merging]
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `kb_id` | 知识库 ID | 省略时自动选择 |
| `--auto` | 自动选择知识库 | False |
| `--exclude` | 排除的知识库 ID（逗号分隔） | 无 |
| `--auto-merging` | 启用 Auto-Merging（合并子节点到父节点） | False |

示例：

```bash
# 指定知识库检索
uv run llamaindex-study search tech_tools "Python 异步编程" -k 5

# 启用 Auto-Merging 检索
uv run llamaindex-study search tech_tools "Python 异步编程" -k 5 --auto-merging

# 自动选择知识库检索
uv run llamaindex-study search "Python 异步编程" --auto -k 5

# 自动选择并排除指定知识库
uv run llamaindex-study search "赖氨酸配比" --auto --exclude tech_tools,academic -k 10
```

### RAG 问答

```bash
uv run llamaindex-study query [<kb_id>] "<问题>" [-k <top_k>] [--auto] [--exclude <kb1,kb2>] [--hyde] [--multi-query] [--auto-merging] [--response-mode <mode>]
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `kb_id` | 知识库 ID | 省略时自动选择 |
| `--auto` | 自动选择知识库 | False |
| `--exclude` | 排除的知识库 ID（逗号分隔） | 无 |
| `--hyde` | 启用 HyDE 查询转换 | False |
| `--multi-query` | 启用多查询转换 | False |
| `--auto-merging` | 启用 Auto-Merging Retriever | False |
| `--response-mode` | 答案生成模式 | 使用配置默认值 |

**答案生成模式选项**：`compact`、`refine`、`tree_summarize`、`simple_summarize`、`no_text`、`accumulate`、`generation`、`compact_accumulate`

示例：

```bash
# 指定知识库问答
uv run llamaindex-study query tech_tools "如何优化 Python 异步代码？"

# 自动选择知识库问答
uv run llamaindex-study query "如何优化异步代码？" --auto

# 启用 HyDE 查询转换
uv run llamaindex-study query tech_tools "Python 异步编程最佳实践" --hyde

# 启用多查询转换
uv run llamaindex-study query tech_tools "如何优化 Python 性能" --multi-query

# 启用 Auto-Merging Retriever
uv run llamaindex-study query tech_tools "Python 异步编程" --auto-merging

# 指定答案生成模式
uv run llamaindex-study query tech_tools "Python 性能优化" --response-mode tree_summarize

# 自动选择并排除指定知识库
uv run llamaindex-study query "猪饲料中氨基酸平衡的关键点是什么？" --auto --exclude zotero_nutrition
```

### 自动路由机制

当使用 `--auto` 或省略 `kb_id` 时：

1. **LLM 意图分类** - 使用 LLM 分析问题内容，自动选择最相关的知识库
2. **关键词匹配降级** - 如果 LLM 不可用，使用关键词匹配 KB 名称和描述
3. **多库并行查询** - 如果问题涉及多个领域，会同时查询多个知识库
4. **结果智能合并** - 按相关性评分合并来自不同知识库的结果

---

## 文档导入 (ingest)

### 导入 Obsidian 笔记

```bash
uv run llamaindex-study ingest obsidian <kb_id> \
    [--vault-path <path>] \
    [--folder-path <folder>] \
    [--recursive] \
    [--rebuild] \
    [--wait]
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--vault-path` | Vault 根路径 | `~/Documents/Obsidian Vault` |
| `--folder-path` | 子文件夹路径 | 根目录 |
| `--recursive` | 递归处理子文件夹 | True |
| `--rebuild` | 重建（清空后重新导入） | False |
| `--force-delete` | 强制删除已有数据 | True |
| `--persist-dir` | 自定义持久化目录 | 空 |
| `--wait` | 同步执行 | False |

示例：

```bash
# 导入整个 Vault（默认 ~/Documents/Obsidian）
uv run llamaindex-study ingest obsidian tech_tools

# 导入特定文件夹
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT

# 递归导入并等待完成
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT --recursive --wait

# 指定 Vault 路径
uv run llamaindex-study ingest obsidian tech_tools --vault-path ~/Documents/MyVault --folder-path IT

# 重建知识库
uv run llamaindex-study ingest obsidian tech_tools --rebuild

# 强制删除已有数据
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT --force-delete
```

### 导入 Zotero 收藏

```bash
uv run llamaindex-study ingest zotero <kb_id> \
    [--collection-id <id>] \
    [--collection-name <name>] \
    [--rebuild] \
    [--wait]
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--collection-id` | Zotero 收藏夹 ID（精确） |
| `--collection-name` | 收藏夹名称（可能模糊匹配） |
| `--rebuild` | 重建知识库 |
| `--wait` | 同步执行 |

示例：

```bash
# 按名称导入
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养饲料理论"

# 按 ID 精确导入
uv run llamaindex-study ingest zotero zotero_nutrition --collection-id 123456

# 重建并导入
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养" --rebuild
```

### 导入单个文件

```bash
uv run llamaindex-study ingest file <kb_id> <file_path> [--wait]
```

示例：

```bash
uv run llamaindex-study ingest file tech_tools /path/to/document.pdf
uv run llamaindex-study ingest file tech_tools README.md
```

### 批量导入

```bash
uv run llamaindex-study ingest batch <kb_id> <path1> <path2> ... [--wait]
```

示例：

```bash
uv run llamaindex-study ingest batch tech_tools ./docs ./notes /tmp/papers
```

### 提交重建任务

```bash
uv run llamaindex-study ingest rebuild <kb_id> [--wait]
```

---

## Obsidian 辅助命令 (obsidian)

### 列出可用 Vault

```bash
uv run llamaindex-study obsidian vaults
```

### 查看 Vault 信息

```bash
uv run llamaindex-study obsidian info <vault_name>
```

示例：

```bash
uv run llamaindex-study obsidian info "默认"
uv run llamaindex-study obsidian info "坚果云同步"
```

### 列出目录映射

```bash
uv run llamaindex-study obsidian mappings
```

### 全库分类导入

```bash
uv run llamaindex-study obsidian import-all \
    [--vault-path <path>] \
    [--rebuild] \
    [--wait]
```

根据配置的映射规则，自动将 Vault 中的文件夹分类导入到不同知识库。

---

## Zotero 辅助命令 (zotero)

### 列出收藏夹

```bash
uv run llamaindex-study zotero collections [--limit <num>]
```

示例：

```bash
uv run llamaindex-study zotero collections --limit 10
```

### 搜索收藏夹

```bash
uv run llamaindex-study zotero search <keyword>
```

示例：

```bash
uv run llamaindex-study zotero search "营养"
```

---

## 任务管理 (task)

### 提交自定义任务

```bash
uv run llamaindex-study task submit <task_type> <kb_id> \
    [--param <key=value>] \
    [--source <source>] \
    [--wait]
```

示例：

```bash
uv run llamaindex-study task submit obsidian tech_tools \
    --param folder_path=IT \
    --param recursive=true \
    --source "cli"
```

### 列出任务

```bash
uv run llamaindex-study task list [--kb-id <kb_id>] [--status <status>] [--limit <num>]
```

状态过滤：`pending`、`running`、`completed`、`failed`、`cancelled`

示例：

```bash
# 列出所有运行中的任务
uv run llamaindex-study task list --status running

# 列出指定知识库的任务
uv run llamaindex-study task list --kb-id tech_tools --limit 10
```

### 查看任务详情

```bash
uv run llamaindex-study task show <task_id>
```

### 取消任务

```bash
uv run llamaindex-study task cancel <task_id>
```

### 删除任务

```bash
uv run llamaindex-study task delete <task_id> [--cleanup]
```

参数说明：

| 参数 | 说明 |
|------|------|
| `task_id` | 任务 ID |
| `--cleanup` | 同时清理关联的知识库数据（dedup 状态），仅对 failed/cancelled 任务有效 |

> ⚠️ 只能删除已完成的、失败的、已取消的任务。正在运行的任务无法删除。
> ⚠️ 使用 `--cleanup` 会清空该知识库的去重状态，可能导致部分数据重新处理。

### 持续观察任务

```bash
uv run llamaindex-study task watch <task_id> [--interval <秒>] [--timeout <秒>]
```

示例：

```bash
# 每 2 秒查看一次
uv run llamaindex-study task watch abc12345 --interval 2

# 最多观察 60 秒
uv run llamaindex-study task watch abc12345 --timeout 60
```

---

## 分类规则 (category)

### 列出规则

```bash
uv run llamaindex-study category rules list
```

### 同步规则到数据库

```bash
uv run llamaindex-study category rules sync
```

### 添加规则

```bash
uv run llamaindex-study category rules add \
    --kb-id <kb_id> \
    --rule-type <type> \
    --pattern <pattern> \
    [--description <desc>] \
    [--priority <num>]
```

规则类型：
- `folder_path`：文件夹路径匹配
- `tag`：标签匹配

示例：

```bash
uv run llamaindex-study category rules add \
    --kb-id tech_tools \
    --rule-type folder_path \
    --pattern "IT" \
    --description "IT 技术文档" \
    --priority 100
```

### 删除规则

```bash
uv run llamaindex-study category rules delete \
    --kb-id <kb_id> \
    --rule-type <type> \
    --pattern <pattern>
```

### 对文件夹分类

```bash
uv run llamaindex-study category classify <folder_path> \
    [--description <desc>] \
    [--use-llm | --no-use-llm]
```

示例：

```bash
# 使用 LLM 智能分类
uv run llamaindex-study category classify /path/to/folder

# 仅使用规则匹配
uv run llamaindex-study category classify /path/to/folder --no-use-llm
```

---

## 管理命令 (admin)

### 列出向量表

```bash
uv run llamaindex-study admin tables
```

### 查看表详情

```bash
uv run llamaindex-study admin table <kb_id>
```

### 删除向量表

```bash
uv run llamaindex-study admin delete-table <kb_id> --yes
```

⚠️ 需要 `--yes` 确认删除。

---

## 配置管理 (config)

### 列出所有配置

```bash
uv run llamaindex-study config list
```

输出示例：

```
============================================================
📁 Embedding
============================================================
  配置项                            值                    说明
  ------------------------------ -------------------- ------------------------------
  OLLAMA_EMBED_MODEL             bge-m3               Embedding 模型名称
  ...

============================================================
📁 检索
============================================================
  配置项                            值                    说明
  ------------------------------ -------------------- ------------------------------
  USE_HYBRID_SEARCH             false                启用混合搜索（向量 + BM25）
  USE_HYDE                       false                启用 HyDE 查询转换
  ...
```

### 获取单个配置

```bash
uv run llamaindex-study config get <key>
```

示例：

```bash
# 查看混合搜索配置
uv run llamaindex-study config get USE_HYBRID_SEARCH

# 查看 HyDE 配置
uv run llamaindex-study config get USE_HYDE
```

### 设置配置

```bash
uv run llamaindex-study config set <key> <value>
```

示例：

```bash
# 启用混合搜索
uv run llamaindex-study config set USE_HYBRID_SEARCH true

# 启用 HyDE
uv run llamaindex-study config set USE_HYDE true

# 设置混合搜索权重
uv run llamaindex-study config set HYBRID_SEARCH_ALPHA 0.7

# 设置响应模式
uv run llamaindex-study config set RESPONSE_MODE refine
```

> ⚠️ 配置会写入 `.env` 文件，部分配置需要重启服务才能生效。

### 常用配置项说明

| 配置项 | 说明 | 可选值 |
|--------|------|--------|
| `USE_HYBRID_SEARCH` | 启用混合搜索（向量 + BM25） | `true`/`false` |
| `HYBRID_SEARCH_ALPHA` | 混合搜索权重（1=仅向量） | `0.0`-`1.0` |
| `USE_HYDE` | 启用 HyDE 查询转换 | `true`/`false` |
| `USE_MULTI_QUERY` | 启用多查询转换 | `true`/`false` |
| `USE_QUERY_REWRITE` | 启用 Query Rewriting | `true`/`false` |
| `RESPONSE_MODE` | 答案生成模式 | `compact`/`refine`/`tree_summarize`/`simple`/`no_text`/`accumulate` |
| `USE_AUTO_MERGING` | 启用 Auto-Merging Retriever | `true`/`false` |
| `USE_SEMANTIC_CHUNKING` | 启用语义分块 | `true`/`false` |
| `USE_RERANKER` | 启用重排序 | `true`/`false` |

---

## 常见使用场景

### 场景 1：首次使用知识库

```bash
# 1. 创建知识库
uv run llamaindex-study kb create tech_tools --name "技术工具" --description "技术文档"

# 2. 导入 Obsidian 笔记
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT --wait

# 3. 开始查询
uv run llamaindex-study query tech_tools "如何配置 Docker？"
```

### 场景 2：增量同步 Obsidian

```bash
# 自动检测变更并增量导入
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT --wait

# 或进入交互模式直接问答
uv run llamaindex-study
```

### 场景 3：Zotero 文献管理

```bash
# 1. 查看可用收藏夹
uv run llamaindex-study zotero collections --limit 20

# 2. 导入收藏夹
uv run llamaindex-study ingest zotero research --collection-name "机器学习" --wait

# 3. 检索文献
uv run llamaindex-study search research "transformer attention"
```

### 场景 4：监控导入任务

```bash
# 1. 提交任务
uv run llamaindex-study ingest obsidian tech_tools

# 输出：{"task_id": "abc12345", "status": "pending", ...}

# 2. 持续观察
uv run llamaindex-study task watch abc12345 --interval 2

# 3. 查看最终结果
uv run llamaindex-study task show abc12345
```

---

## 独立导入脚本

除了 `llamaindex-study` CLI，项目还提供独立的导入脚本，用于特定场景的批量导入。

### Obsidian 批量导入

```bash
uv run python -m kb.ingest                    # 导入所有知识库
uv run python -m kb.ingest --list           # 列出所有知识库状态
uv run python -m kb.ingest --kb tech_tools   # 只导入指定知识库
uv run python -m kb.ingest --rebuild         # 重建所有知识库
uv run python -m kb.ingest --verbose         # 显示详细信息
```

### Zotero 导入（特定收藏）

```bash
uv run python -m kb.ingest_zotero              # 增量导入"营养饲料理论"收藏
uv run python -m kb.ingest_zotero --rebuild   # 强制重建
uv run python -m kb.ingest_zotero --status     # 查看导入状态
uv run python -m kb.ingest_zotero --batch-size 50  # 每批节点数
```

### 高新历史项目导入

```bash
uv run python -m kb.ingest_hitech_history              # 增量导入
uv run python -m kb.ingest_hitech_history --rebuild   # 强制重建
uv run python -m kb.ingest_hitech_history --status     # 查看导入状态
```

> ⚠️ 注意：`kb.ingest_zotero` 和 `kb.ingest_hitech_history` 是针对特定数据源硬编码的脚本，不适合通用场景。推荐使用 `llamaindex-study ingest` 系列命令。

---

## 环境变量

CLI 工具读取以下环境变量（参见 `.env.example`）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SILICONFLOW_API_KEY` | 硅基流动 API Key | - |
| `SILICONFLOW_MODEL` | LLM 模型 | `Pro/deepseek-ai/DeepSeek-V3.2` |
| `OLLAMA_EMBED_MODEL` | Embedding 模型 | `bge-m3` |
| `OLLAMA_LOCAL_URL` | 本地 Ollama | `http://localhost:11434` |
| `OLLAMA_REMOTE_URL` | 远程 Ollama | 空（禁用） |
| `OBSIDIAN_VAULT_ROOT` | Obsidian Vault 根目录 | `~/Documents/Obsidian Vault` |
| `PERSIST_DIR` | 向量存储目录 | `~/.llamaindex/storage` |
