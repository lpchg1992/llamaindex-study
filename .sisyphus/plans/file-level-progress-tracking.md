# 文件级进度跟踪架构设计

## 问题背景

当前任务进度跟踪粒度为"文件级别"，存在以下问题：

1. **精度不足**: 进度按文件数计算，不反映实际 chunk 处理量
2. **状态模糊**: 不区分"处理中"、"写入成功"、"写入失败"等子状态
3. **无法细粒度控制**: 用户不能暂停/取消/删除单个文件
4. **缺少写入确认**: 不知道文件是否真正写入数据库

## 目标

1. **精确进度**: 按 chunk 数量计算百分比（total_chunks, processed_chunks）
2. **写入确认**: 每个文件明确标记 `db_written: true/false`
3. **文件状态机**: pending → processing → embedding → writing → completed/failed
4. **细粒度操作**: 任务详情页展示每个文件的状态，支持单独取消/跳过

## 架构设计

### 1. 数据模型

#### TaskRecord 新增字段

```python
# task_queue.py - TaskRecord
file_progress: Mapped[str] = mapped_column(Text, nullable=True)
# JSON 结构: List[FileProgressItem]
```

#### FileProgressItem 数据结构

```python
@dataclass
class FileProgressItem:
    file_id: str          # 唯一标识（文件路径或 item_id 的 hash）
    file_name: str        # 显示名称
    status: str           # pending | processing | embedding | writing | completed | failed | cancelled
    total_chunks: int    # 总 chunk 数
    processed_chunks: int # 已处理 chunk 数
    db_written: bool      # 是否已写入数据库
    error: Optional[str]  # 错误信息
    started_at: Optional[float]
    completed_at: Optional[float]
```

### 2. TaskQueue 新增接口

```python
class TaskQueue:
    def update_file_progress(
        self,
        task_id: str,
        file_id: str,
        status: str = None,
        processed_chunks: int = None,
        total_chunks: int = None,
        db_written: bool = None,
        error: str = None,
    ):
        """更新单个文件的进度"""

    def get_file_progress(self, task_id: str) -> List[FileProgressItem]:
        """获取任务的所有文件进度"""

    def cancel_file(self, task_id: str, file_id: str) -> bool:
        """取消单个文件（标记为 cancelled，后续跳过）"""

    def set_file_progress_total(self, task_id: str, files: List[FileProgressItem]):
        """初始化文件列表（在任务开始时调用）"""
```

### 3. 任务执行器改造

#### `_execute_selective` 改造

```python
async def _execute_selective(self, task: "Task") -> None:
    # 1. 初始化文件列表
    files = [FileProgressItem(file_id=..., file_name=..., ...) for item in items]
    self.queue.set_file_progress_total(task_id, files)

    # 2. 更新整体进度
    total_chunks = sum(f.total_chunks for f in files)
    self.queue.update_progress(task_id, total=total_chunks)

    for i, item in enumerate(items):
        # 检查文件是否被单独取消
        if self._is_file_cancelled(task_id, file_id):
            continue

        # 更新文件状态: processing
        self.queue.update_file_progress(task_id, file_id, status="processing")

        # 嵌入
        self.queue.update_file_progress(task_id, file_id, status="embedding")
        # ... embedding 完成后更新 processed_chunks

        # 写入
        self.queue.update_file_progress(task_id, file_id, status="writing")
        # ... 写入后设置 db_written=True

        # 完成
        self.queue.update_file_progress(task_id, file_id, status="completed")

        # 更新整体 chunk 进度
        self.queue.update_progress(
            task_id,
            current=sum_processed_chunks,
            total=total_chunks,
            message=f"[{i+1}/{len(items)}] 处理: {item_type} - {item_id}"
        )

    # 最终状态判断
    self.queue.complete_task(task_id, result={...})
```

#### 新增文件取消检查

```python
def _is_file_cancelled(self, task_id: str, file_id: str) -> bool:
    """检查单个文件是否被取消"""
    files = self.queue.get_file_progress(task_id)
    for f in files:
        if f.file_id == file_id and f.status == "cancelled":
            return True
    return False
```

### 4. WebSocket 推送改造

#### 消息格式扩展

```python
{
    "type": "task_update",
    "task_id": "xxx",
    "data": {
        "status": "running",
        "progress": 45,
        "current": 450,
        "total": 1000,
        "message": "处理 15/30 文件 (450/1000 chunks)",
        "file_progress": [  # 新增字段
            {
                "file_id": "abc",
                "file_name": "paper.pdf",
                "status": "completed",
                "total_chunks": 50,
                "processed_chunks": 50,
                "db_written": True,
                "error": None
            },
            ...
        ]
    }
}
```

### 5. 前端改造

#### TaskResponse 类型扩展

```typescript
// api.ts
interface TaskResponse {
    // ... 现有字段
    result?: {
        // ... 现有字段
        file_progress?: FileProgressItem[]
    }
}
```

#### TaskDetailDialog 改造

```typescript
function TaskDetailDialog({ taskId, open, onOpenChange }: TaskDetailDialogProps) {
    // 显示文件列表，each file has:
    // - 文件名 + 状态 Badge
    // - Chunk 进度条 (processed_chunks / total_chunks)
    // - DB 写入状态图标
    // - 取消按钮（running 时可点击）
}
```

## 实施步骤

### Phase 1: 数据模型和队列接口

1. [ ] 在 `kb/task_queue.py` 添加 `FileProgressItem` dataclass
2. [ ] 在 `TaskRecord` 添加 `file_progress` 字段
3. [ ] 实现 `update_file_progress()`, `get_file_progress()`, `set_file_progress_total()`, `cancel_file()`
4. [ ] 添加数据库迁移逻辑（处理 `file_progress` 列）

### Phase 2: 执行器集成

5. [ ] 改造 `_execute_selective`: 初始化文件列表，每阶段更新文件状态
6. [ ] 改造 `_execute_obsidian`: 同样支持文件级跟踪
7. [ ] 改造 `_execute_generic`: 同样支持文件级跟踪
8. [ ] 计算进度时基于 chunk 而非文件数

### Phase 3: WebSocket 和 API

9. [ ] 修改 `send_task_update` 支持 `file_progress` 字段
10. [ ] 修改 `TaskResponse` Pydantic 模型
11. [ ] `get_task` API 返回完整的 `file_progress`

### Phase 4: 前端

12. [ ] 更新 `TaskResponse` TypeScript 类型
13. [ ] 改造 `TaskDetailDialog` 显示文件列表
14. [ ] 添加单个文件取消功能（调用 `DELETE /tasks/{task_id}/files/{file_id}`）

## 关键设计决策

### 1. 文件 ID 生成

使用 `hash(file_path + item_id)` 作为唯一标识，确保重试时 ID 稳定。

### 2. 取消语义

- `cancel_file`: 标记文件为 `cancelled` 状态，执行器在下次循环检查时跳过
- 不支持真正的"暂停"单个文件（需要复杂的状态机）
- 取消操作是异步的，不等待当前文件完成

### 3. 进度计算

```
整体进度 = sum(processed_chunks for all files) / sum(total_chunks for all files) * 100
```

### 4. 数据库写入确认

在 `write_nodes_sync` 返回成功后才设置 `db_written=True`，确保数据真正持久化。

## 风险和限制

1. **向后兼容**: `file_progress` 为可选字段，旧任务不受影响
2. **性能**: 每文件更新都写数据库，可能影响大量文件的性能
   - 解决: 批量更新，每 5 个文件刷一次或每 10 秒刷一次
3. **前端复杂度**: 文件列表可能很长，需要虚拟滚动
