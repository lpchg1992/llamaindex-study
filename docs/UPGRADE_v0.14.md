# LlamaIndex 升级文档 (v0.10 → v0.14)

## 升级概述

本次升级将 LlamaIndex 从 v0.10.x 升级到 v0.14.19，解决了多个版本遗留的兼容性问题，并使项目跟上最新特性。

## 升级内容

### 依赖版本变更

| 组件 | 旧版本 | 新版本 |
|------|--------|--------|
| `llama-index-core` | `>=0.10.0` | `>=0.14.0` |
| `llama-index-llms-openai` | `>=0.1.0` | `>=0.3.0` |
| `llama-index-embeddings-ollama` | `>=0.1.0` | `>=0.3.0` |
| `llama-index-vector-stores-lancedb` | `>=0.5.0,<0.6.0` | `>=0.5.0,<0.6.0` (保持) |
| `llama-index-vector-stores-chroma` | `>=0.5.3,<0.6.0` | `>=0.5.0,<0.6.0` |
| `llama-index-readers-file` | `>=0.6.0,<0.7.0` | `>=0.6.0,<0.7.0` (保持) |
| `lancedb` | `>=0.30.1,<0.31.0` | `>=0.6.0,<1.0.0` |

### Qdrant 支持变更

由于 Qdrant 相关的 `llama-index-vector-stores-qdrant` 尚未支持 Python 3.14，该功能暂时禁用。

**如需使用 Qdrant，请确保 Python 版本 < 3.14。**

## 已知问题

### 1. SimpleDirectoryReader 隐藏文件过滤

在新版本中，`SimpleDirectoryReader` 默认排除隐藏文件。如果遇到 "No files found" 错误，请使用：

```python
from llama_index.core import SimpleDirectoryReader

docs = SimpleDirectoryReader(
    directory,
    exclude_hidden=False  # 禁用隐藏文件过滤
).load_data()
```

### 2. 项目代码无需修改

项目现有代码已正确使用新版 LlamaIndex API：
- ✅ `Settings` 而非废弃的 `ServiceContext`
- ✅ `VectorStoreIndex.from_vector_store()` 而非旧版方式
- ✅ `BaseNodePostprocessor` 重排序接口兼容

## 测试

项目提供了完整的升级测试脚本：

```bash
# 运行基础导入测试
poetry run python .test_llamaindex/test_upgrade.py

# 完整功能测试（需要有效的 SiliconFlow API Key）
# 编辑 .test_llamaindex/.env.test 设置有效的 API Key
```

## 升级步骤

1. 更新依赖：
```bash
poetry update llama-index-core llama-index-llms-openai llama-index-embeddings-ollama
```

2. 运行测试：
```bash
poetry run python .test_llamaindex/test_upgrade.py
```

3. 验证核心功能（向量检索、RAG）

## 配置说明

### 测试环境

测试使用独立的目录，避免污染生产数据：
- 测试存储目录：`.test_llamaindex/storage`
- 测试数据目录：`.test_llamaindex/test_docs`
- 测试配置文件：`.test_llamaindex/.env.test`

### 生产环境

生产环境使用 `.env` 文件配置，升级后无需修改配置项。

## 变更记录

- **2026-03-30**: 完成升级验证，llama-index-core 升级到 0.14.19
