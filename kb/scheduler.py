#!/usr/bin/env python3
"""
调度器独立进程

作为独立进程运行任务调度器，确保任务在后台持续执行。
可以通过 `python -m kb.scheduler` 或 `uv run llamaindex-study scheduler` 运行。
"""

import asyncio
import os
import sys
from pathlib import Path

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from kb.task_executor import (
    TaskScheduler,
    write_scheduler_pid,
    cleanup_scheduler_pid,
    get_scheduler_pid_file,
)


def main():
    print(f"调度器启动 (PID: {os.getpid()})")

    # 写入 PID 文件
    write_scheduler_pid()

    try:
        # 运行调度器
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        scheduler = TaskScheduler()
        loop.run_until_complete(scheduler.run())
    except KeyboardInterrupt:
        print("调度器收到停止信号")
    finally:
        # 清理 PID 文件
        cleanup_scheduler_pid()
        print("调度器已停止")


if __name__ == "__main__":
    import os

    main()
