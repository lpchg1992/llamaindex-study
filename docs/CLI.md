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
| `/search <query>` | 检索（需配合 --kb-ids 指定知识库） |
| `/query <question>` | 问答（需配合 --kb-ids 指定知识库） |
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
  model                         模型管理
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
uv run llamaindex-study kb create <kb_id> --name <名称> [--description <描述>] [--source-type <类型>]
```

参数说明：
- `kb_id`: 知识库唯一标识
- `--name`: 知识库显示名称（必填）
- `--description`: 知识库描述（可选）
- `--source-type`: 知识库来源类型（可选，默认 `generic`）
  - `generic`: 通用知识库
  - `zotero`: Zotero 文献库（数据存储到 Zotero 专用目录）
  - `obsidian`: Obsidian 笔记库
  - `manual`: 手动创建

示例：

```bash
# 创建通用知识库
uv run llamaindex-study kb create my_kb --name "我的知识库" --description "个人文档"

# 创建 Zotero 文献库
uv run llamaindex-study kb create my_zotero --name "我的文献库" --source-type zotero

# 创建 Obsidian 笔记库
uv run llamaindex-study kb create my_obsidian --name "我的笔记库" --source-type obsidian
```

### 删除知识库

```bash
uv run llamaindex-study kb delete <kb_id> --yes
```

⚠️ 需要 `--yes` 确认删除。

### 初始化知识库

```bash
uv run llamaindex-study kb initialize <kb_id>
```

**作用**：清空知识库的所有数据（向量数据和去重记录），但保留知识库的配置（元数据）。

**执行后果**：
- 删除知识库中的所有向量数据（无法通过命令恢复）
- 清空去重状态记录
- 知识库配置（名称、描述、标签）保留

**与 `ingest rebuild` 的区别**：
| 命令 | 作用 |
|------|------|
| `kb initialize` | **只清空数据**，不重新导入，需要手动执行 `ingest` 导入 |
| `ingest rebuild` | **清空后重新导入**，完整重建知识库 |

**示例**：

```bash
# 清空知识库所有数据（保留配置）
uv run llamaindex-study kb initialize tech_tools

# 之后再手动导入
uv run llamaindex-study ingest obsidian tech_tools
```

### 知识库一致性校验

校验知识库数据一致性，确保 dedup 记录与 LanceDB 实际向量数据匹配。

```bash
# 校验单个知识库
uv run llamaindex-study kb consistency <kb_id>

# 校验所有知识库
uv run llamaindex-study kb consistency

# 校验并自动修复
uv run llamaindex-study kb consistency <kb_id> --repair

# 指定修复模式
uv run llamaindex-study kb consistency <kb_id> --mode sync
```

| 参数 | 说明 |
|------|------|
| `kb_id` | 知识库 ID（省略则检查所有） |
| `--repair` | 自动修复不一致（等同于 `--mode sync`） |
| `--mode` | 修复模式：`sync`（删除orphan）、`rebuild`（重建）、`dry`（只报告，默认） |

**修复模式说明：**

| 模式 | 说明 |
|------|------|
| `dry` | 只报告差异，不修复（默认） |
| `sync` | 删除 LanceDB 中的 orphan 向量（多余数据） |
| `rebuild` | 重新扫描文件，需要重新导入 |

**示例输出：**

```
============================================================
📊 知识库一致性校验: animal_nutrition_breeding
============================================================
  Dedup 记录: 221 文件, 1247 chunks
  LanceDB:    1247 行
  状态: ✅ 一致
============================================================
```

### 知识库主题分析

分析知识库内容，使用 LLM 提取 15-30 个专业主题词，用于**自动路由**时的知识库选择。

**Topics 用途**：
- 自动路由时，LLM 根据问题内容匹配各 KB 的 topics
- 关键词匹配路由时，query 分词后匹配 topics 计算得分

**自动生成**：文档导入完成后会自动提取 topics。优先使用远程 LLM，若超时/失败会回退到统计提取，避免 topics 为空。

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

> `kb topics` / `kb topics-local` 是唯一主题分析入口。

---

## 检索查询

### 向量检索

```bash
uv run llamaindex-study search "<查询词>" --kb-ids <kb1,kb2> [-k <top_k>] [--embed-model-id <model_id>] [--auto-merging|--no-auto-merging]
uv run llamaindex-study search "<查询词>" --auto [-k <top_k>] [--exclude <kb1,kb2>] [--embed-model-id <model_id>] [--auto-merging|--no-auto-merging]
```

参数说明：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--vault-path` | Vault 根路径 | `OBSIDIAN_VAULT_ROOT` 环境变量，或 `~/Documents/Obsidian Vault` |
| `--folder-path` | 子文件夹路径（相对于 Vault 根目录） | 根目录 |
| `--recursive` | 递归处理子文件夹 | True |
| `--rebuild` | **清空后重新导入**。启用后，会先删除知识库中的所有向量数据和去重记录，再重新导入指定的文件夹 | False |
| `--force-delete` | 同步时处理已删除的文件。当源文件被删除时，是否从向量库中移除对应的数据 | True |
| `--persist-dir` | 自定义持久化目录（通常不需要指定） | 空 |
| `--refresh-topics/--no-refresh-topics` | 导入后是否刷新 topics | True |

示例：

```bash
# 导入整个 Vault（默认 ~/Documents/Obsidian）
uv run llamaindex-study ingest obsidian tech_tools

# 导入特定文件夹
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT

# 递归导入
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT --recursive

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
    [--refresh-topics|--no-refresh-topics] \
    [--chunk-strategy {hierarchical,sentence,semantic}] \
    [--chunk-size <size>] \
    [--hierarchical-sizes <sizes>]
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--collection-id` | Zotero 收藏夹 ID（精确） |
| `--collection-name` | 收藏夹名称（可能模糊匹配） |
| `--rebuild` | **清空后重新导入**。启用后，会先删除知识库中的所有向量数据和去重记录，再重新导入该收藏夹的文献 |
| `--refresh-topics/--no-refresh-topics` | 导入后是否刷新 topics |
| `--chunk-strategy` | 分块策略：`hierarchical`（默认）/ `sentence` / `semantic` |
| `--chunk-size` | 分块大小（默认: 1024） |
| `--hierarchical-sizes` | hierarchical 模式分层大小，逗号分隔（默认: 2048,1024,512）|

示例：

```bash
# 按名称导入（默认 hierarchical 分块）
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养饲料理论"

# 按 ID 精确导入
uv run llamaindex-study ingest zotero zotero_nutrition --collection-id 123456

# 重建并导入
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养" --rebuild

# 使用 sentence 分块策略
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养" --chunk-strategy sentence

# 使用 sentence 分块策略并指定大小
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养" --chunk-strategy sentence --chunk-size 2048

# 使用 hierarchical 分块策略并自定义分层大小
uv run llamaindex-study ingest zotero zotero_nutrition --collection-name "营养" --chunk-strategy hierarchical --hierarchical-sizes 4096,2048,1024
```

### 导入单个文件

```bash
uv run llamaindex-study ingest file <kb_id> <file_path> \
    [--refresh-topics|--no-refresh-topics]
```

> **验证**：提交任务前会检查路径是否存在、是否为有效文件/目录，以及目录中是否有可处理的文件。如果没有找到文件，命令会报错而不会提交空任务。

示例：

```bash
uv run llamaindex-study ingest file tech_tools /path/to/document.pdf
uv run llamaindex-study ingest file tech_tools README.md
```

### 批量导入

```bash
uv run llamaindex-study ingest batch <kb_id> <path1> <path2> ... \
    [--include pdf,md] [--exclude xlsx] \
    [--refresh-topics|--no-refresh-topics]
```

> **验证**：提交任务前会检查所有路径是否存在，并统计可处理的文件总数。如果所有路径都不存在或没有可处理的文件，命令会报错而不会提交空任务。

示例：

```bash
uv run llamaindex-study ingest batch tech_tools ./docs ./notes /tmp/papers
```

### 提交重建任务

```bash
uv run llamaindex-study ingest rebuild <kb_id> \
    [--refresh-topics|--no-refresh-topics]
```

**作用**：清空知识库后，按照知识库配置中记录的源路径重新导入所有文档。

**执行后果**：
- 清空知识库中的所有向量数据
- 清空去重状态记录
- 重新扫描源路径并导入所有文档

**与 `kb initialize` 的区别**：
| 命令 | 作用 |
|------|------|
| `kb initialize` | **只清空数据**，不重新导入 |
| `ingest rebuild` | **清空后重新导入**，完整重建知识库 |

**使用场景**：
- 当知识库数据损坏或不一致时
- 当需要重新处理所有文档（更换分块策略等）时
- 当源文档有大幅变更需要完全重新索引时

**示例**：

```bash
# 完整重建知识库（清空后重新导入）
uv run llamaindex-study ingest rebuild tech_tools
```

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
   
```

**作用**：根据配置的映射规则，自动将 Vault 中的文件夹分类导入到不同知识库。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--vault-path` | Vault 根路径 | `~/Documents/Obsidian Vault` |
| `--rebuild` | **清空后重新导入**。启用后，会先删除所有相关知识库中的向量数据和去重记录，再重新导入 | False |

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

> 执行 `task list` 会自动清理孤儿任务（运行中但实际无后台进程的任务）。

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

> 取消正在运行的任务。任务会在当前文件处理完成后进入已取消状态。

### 暂停任务

```bash
uv run llamaindex-study task pause <task_id>
```

> 暂停正在运行的任务，任务会在当前文件处理完成后进入暂停状态。

### 恢复任务

```bash
uv run llamaindex-study task resume <task_id>
```

> 恢复已暂停的任务，继续执行。只能恢复通过 `task pause` 暂停的任务。

### 暂停所有任务

```bash
uv run llamaindex-study task pause-all [--status running]
```

> 暂停所有运行中的任务。

### 恢复所有任务

```bash
uv run llamaindex-study task resume-all
```

> 恢复所有已暂停的任务。

### 删除任务

```bash
uv run llamaindex-study task delete <task_id> [--cleanup]
```

**作用**：删除任务记录（从任务队列数据库中移除）。

| 参数 | 说明 |
|------|------|
| `task_id` | 任务 ID（从 `task list` 获取） |
| `--cleanup` | 删除任务时，同时清理该任务关联的知识库数据 |

**`--cleanup` 执行后果**：
- 删除任务记录
- 删除该任务导入的源文件对应的**去重记录**
- 删除该任务导入的源文件对应的**向量数据**

**注意**：
- ⚠️ 只能删除 `completed`、`failed`、`cancelled` 状态的任务
- ⚠️ `running` 状态的任务需要先 `task cancel` 再删除
- ⚠️ `--cleanup` 只清理该任务产生的源文件数据，不影响其他任务导入的数据

### 删除所有任务

```bash
uv run llamaindex-study task delete-all [--status completed] [--cleanup]
```

**作用**：批量删除任务记录。

| 参数 | 说明 |
|------|------|
| `--status` | 筛选任务状态（pending/running/completed/failed/cancelled），默认 `completed` |
| `--cleanup` | 删除任务时，同时清理关联的知识库数据（去重记录 + 向量数据） |

**示例**：

```bash
# 删除所有已完成的任务
uv run llamaindex-study task delete-all

# 删除所有失败的任务
uv run llamaindex-study task delete-all --status failed

# 删除所有任务并清理关联数据
uv run llamaindex-study task delete-all --status completed --cleanup
```

### 清理孤儿任务

```bash
uv run llamaindex-study task cleanup [--no-cleanup]
```

**作用**：清理孤儿任务（状态为 running 但实际无后台进程执行的任务）。

**何时需要**：当执行进程被强制终止（kill -9、崩溃等）时，数据库中的任务状态仍为 `running`，需要用此命令清理。

| 参数 | 说明 |
|------|------|
| `--no-cleanup` | 仅标记孤儿任务为 failed，不清理关联的向量数据 |

**执行后果**：
- 默认：标记孤儿任务为 `failed` **并清理**关联的向量数据
- `--no-cleanup`：仅标记孤儿任务为 `failed`，不清理数据

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

**作用**：直接删除知识库的向量表（物理删除 LanceDB 表）。

**执行后果**：
- 删除知识库中的所有向量数据（无法通过命令恢复）
- 不影响知识库配置（元数据保留在数据库中）
- 不清空去重记录

**与 `kb initialize` 的区别**：
| 命令 | 向量数据 | 去重记录 | 知识库配置 |
|------|----------|----------|------------|
| `admin delete-table` | 删除 | 保留 | 保留 |
| `kb initialize` | 删除 | 删除 | 保留 |

**使用场景**：
- 知识库向量数据损坏时
- 需要重置向量存储时

**示例**：

```bash
# 删除向量表（需要确认）
uv run llamaindex-study admin delete-table tech_tools --yes
```

---

## 供应商管理 (vendor)

供应商管理命令用于管理模型供应商（如 SiliconFlow、Ollama）。

### 列出所有供应商

```bash
uv run llamaindex-study vendor list
```

输出示例：

```
id           name         api_base                       is_active
-----------  -----------  -----------------------------  ---------
ollama       Ollama       http://localhost:11434         True
siliconflow  SiliconFlow  https://api.siliconflow.cn/v1  True
```

### 添加供应商

```bash
uv run llamaindex-study vendor add <vendor_id> [options]
```

参数：
- `vendor_id`: 供应商ID，如 `siliconflow`, `ollama`

选项：
- `--name <name>`: 显示名称
- `--api-base <url>`: API端点
- `--api-key <key>`: API密钥（Ollama不需要）

示例：

```bash
# 添加 SiliconFlow 供应商
uv run llamaindex-study vendor add siliconflow --name "SiliconFlow" \
  --api-base "https://api.siliconflow.cn/v1" \
  --api-key "your-api-key"

# 添加 Ollama 供应商
uv run llamaindex-study vendor add ollama --name "Ollama" \
  --api-base "http://localhost:11434"
```

### 删除供应商

```bash
uv run llamaindex-study vendor remove <vendor_id>
```

示例：

```bash
uv run llamaindex-study vendor remove ollama
```

### 设置供应商激活状态

```bash
uv run llamaindex-study vendor set-active <vendor_id> [--enable|--disable]
```

示例：

```bash
# 禁用供应商
uv run llamaindex-study vendor set-active siliconflow --disable

# 启用供应商
uv run llamaindex-study vendor set-active siliconflow --enable
```

---

## 模型管理 (model)

模型管理命令用于管理 LLM/Embedding/Reranker 模型，支持 siliconflow、ollama 等供应商。

### 列出所有模型

```bash
uv run llamaindex-study model list
uv run llamaindex-study model list --type llm
uv run llamaindex-study model list --type embedding
```

输出示例：

```
id                                         vendor_id      name                           type       is_default  is_active
-----------------------------------------  -------------  -----------------------------  ---------  ----------  ---------
ollama/bge-m3:latest                       ollama         bge-m3:latest                  embedding  True        True
ollama_homepc/bge-m3:latest                ollama_homepc  bge-m3:latest                  embedding  False       True
siliconflow/Pro/deepseek-ai/DeepSeek-V3.2  siliconflow    Pro/deepseek-ai/DeepSeek-V3.2  llm        True        True
ollama/lfm2.5-thinking:latest              ollama         lfm2.5-thinking:latest         llm        False       True
```

### 添加模型

```bash
uv run llamaindex-study model add <model_id> [options]
```

参数：
- `model_id`: 模型ID，格式 `{vendor_id}/{model-name}`，如 `siliconflow/DeepSeek-V3.2`

选项：
- `--vendor-id <id>`: 供应商ID（必填）
- `--name <name>`: 显示名称
- `--type <type>`: 模型类型 (`llm`, `embedding`, `reranker`)，默认 `llm`
- `--set-default`: 设为默认模型

示例：

```bash
# 添加 Ollama LLM 模型
uv run llamaindex-study model add ollama/lfm2.5-thinking:latest \
  --vendor-id ollama --name "LFM 2.5 Thinking" --type llm

# 添加 Ollama Embedding 模型
uv run llamaindex-study model add ollama/bge-m3:latest \
  --vendor-id ollama --name "BGE-M3" --type embedding --set-default

# 添加远程 Embedding 模型
uv run llamaindex-study model add ollama_homepc/bge-m3:latest \
  --vendor-id ollama_homepc --name "BGE-M3 (HomePC)" --type embedding

# 添加 SiliconFlow 模型并设为默认
uv run llamaindex-study model add siliconflow/DeepSeek-V3.2 \
  --vendor-id siliconflow --name "DeepSeek V3.2" --type llm --set-default
```

### 删除模型

```bash
uv run llamaindex-study model remove <model_id>
```

示例：

```bash
uv run llamaindex-study model remove ollama/lfm2.5-thinking:latest
```

### 设置默认模型

```bash
uv run llamaindex-study model set-default <model_id>
```

示例：

```bash
uv run llamaindex-study model set-default siliconflow/DeepSeek-V3.2
```

### 在查询中使用指定模型

```bash
uv run llamaindex-study query <kb_id> "<question>" --model-id <model_id>
```

示例：

```bash
# 使用指定模型进行问答
uv run llamaindex-study query tech_tools "如何优化Python性能？" --model-id ollama/lfm2.5-thinking:latest
```

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
| `MULTI_QUERY_NUM` | 多查询生成变体数量 | 整数（默认 3） |
| `USE_QUERY_REWRITE` | 启用 Query Rewriting | `true`/`false` |
| `RESPONSE_MODE` | 答案生成模式 | `compact`/`refine`/`tree_summarize`/`simple`/`no_text`/`accumulate` |
| `USE_AUTO_MERGING` | 启用 Auto-Merging Retriever | `true`/`false` |
| `USE_SEMANTIC_CHUNKING` | 启用语义分块 | `true`/`false` |
| `USE_RERANKER` | 启用重排序 | `true`/`false` |

> **组合使用**：HyDE（`USE_HYDE`）、多查询转换（`USE_MULTI_QUERY`）、Auto-Merging（`USE_AUTO_MERGING`）可以任意组合同时启用，组合使用会获得更好的检索质量。

---

## 常见使用场景

### 场景 1：首次使用知识库

```bash
# 1. 创建知识库
uv run llamaindex-study kb create tech_tools --name "技术工具" --description "技术文档"

# 2. 导入 Obsidian 笔记
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT

# 3. 开始查询
uv run llamaindex-study query tech_tools "如何配置 Docker？"
```

### 场景 2：增量同步 Obsidian

```bash
# 自动检测变更并增量导入
uv run llamaindex-study ingest obsidian tech_tools --folder-path IT

# 或进入交互模式直接问答
uv run llamaindex-study
```

### 场景 3：Zotero 文献管理

```bash
# 1. 查看可用收藏夹
uv run llamaindex-study zotero collections --limit 20

# 2. 导入收藏夹
uv run llamaindex-study ingest zotero research --collection-name "机器学习"

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
```

> 该脚本为统一导入编排链路的专用入口。

### Zotero 导入（特定收藏）

```bash
uv run python -m kb.ingest_zotero --kb-id zotero_nutrition --collection-name "营养饲料理论"
uv run python -m kb.ingest_zotero --kb-id zotero_nutrition --collection-id 12345 --rebuild
uv run python -m kb.ingest_zotero --kb-id zotero_nutrition --status
```

> ⚠️ 注意：以上脚本和 `llamaindex-study ingest` 使用同一套导入编排服务，语义一致。  
> 对于任意非 Obsidian / Zotero 的业务导入，统一使用 `ingest file` 或 `ingest batch`。

---

## 环境变量

CLI 工具读取以下环境变量（参见 `.env.example`）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SILICONFLOW_API_KEY` | 硅基流动 API Key | - |
| `SILICONFLOW_MODEL` | LLM 模型 | `Pro/deepseek-ai/DeepSeek-V3.2` |
| `OLLAMA_EMBED_MODEL` | Embedding 模型 | `bge-m3` |
| `OLLAMA_LOCAL_URL` | 本地 Ollama（仅作 fallback） | `http://localhost:11434` |
| `OLLAMA_REMOTE_URL` | 备用 Ollama（仅作 fallback） | 空 |
| `OBSIDIAN_VAULT_ROOT` | Obsidian Vault 根目录 | `~/Documents/Obsidian Vault` |
| `PERSIST_DIR` | 向量存储目录（通用 KB） | `/Volumes/online/llamaindex` |
| `ZOTERO_PERSIST_DIR` | Zotero 存储目录 | `/Volumes/online/llamaindex/zotero` |
| `CHUNK_STRATEGY` | 分块策略 | `hierarchical` |
| `CHUNK_SIZE` | 默认分块大小 | `1024` |
| `CHUNK_OVERLAP` | 默认分块重叠 | `100` |
| `HIERARCHICAL_CHUNK_SIZES` | 层级分块各层大小 | `2048,1024,512` |
| `SENTENCE_CHUNK_SIZE` | 句子分块大小 | `1024` |
| `SENTENCE_CHUNK_OVERLAP` | 句子分块重叠 | `100` |
