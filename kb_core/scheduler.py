#!/usr/bin/env python3
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rag.logger import configure_all_loggers, get_log_dir
from kb_core.task_executor import (
    TaskScheduler,
    write_scheduler_pid,
    cleanup_scheduler_pid,
)


def main():
    print(f"调度器启动 (PID: {os.getpid()})")

    configure_all_loggers(get_log_dir(), level=logging.INFO)

    write_scheduler_pid()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        scheduler = TaskScheduler()
        loop.run_until_complete(scheduler.run())
    except KeyboardInterrupt:
        print("调度器收到停止信号")
    finally:
        cleanup_scheduler_pid()
        print("调度器已停止")


if __name__ == "__main__":
    main()
