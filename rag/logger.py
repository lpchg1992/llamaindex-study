"""
日志工具模块

提供统一的日志配置，支持：
- 控制台彩色输出（开发友好）
- 文件日志（持久化记录）
- 模块级 logger 获取
- 自动日志文件管理
"""

import logging
import sys
import threading
from pathlib import Path
from typing import Optional
from datetime import datetime


# 日志格式
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
FILE_FORMAT = (
    "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# 日志级别（支持环境变量覆盖）
def _get_log_level() -> int:
    import os

    level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(level_str, logging.INFO)


LOG_LEVEL = _get_log_level()

# 全局日志目录
_log_dir: Optional[Path] = None
_log_dir_lock = threading.Lock()


def set_log_dir(log_dir: Path) -> None:
    """设置全局日志目录（线程安全）"""
    global _log_dir
    with _log_dir_lock:
        _log_dir = Path(log_dir)
        _log_dir.mkdir(parents=True, exist_ok=True)


def get_log_dir() -> Path:
    """获取全局日志目录"""
    global _log_dir
    if _log_dir is None:
        from rag.config import get_settings

        settings = get_settings()
        _log_dir = Path(settings.data_dir) / "logs"
        _log_dir.mkdir(parents=True, exist_ok=True)
    return _log_dir


def get_task_log_file(task_id: str) -> Path:
    today = datetime.now().strftime("%Y%m%d")
    log_dir = get_log_dir()
    return log_dir / f"task_{today}.log"


def setup_task_logger(
    name: str, task_id: str, level: int = LOG_LEVEL
) -> logging.Logger:
    """为任务创建专用的 logger，同时输出到控制台和任务日志文件"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(
        _ColoredFormatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT.split(" ")[1])
    )
    logger.addHandler(console_handler)

    task_handler = TaskLogHandler(task_id)
    task_handler.setLevel(level)
    task_handler.setFormatter(
        logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT.split(" ")[1])
    )
    logger.addHandler(task_handler)

    return logger


def configure_all_loggers(log_dir: Path, level: int = LOG_LEVEL) -> None:
    """配置所有 llamaindex 模块的 logger 写入共享日志文件"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    main_log_file = log_dir / f"llamaindex_{today}.log"

    file_handler = logging.FileHandler(main_log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT))

    modules = ["llamaindex", "llamaindex.kb", "llamaindex.api"]
    for module in modules:
        logger = logging.getLogger(module)
        logger.setLevel(level)
        if not any(
            isinstance(h, logging.FileHandler) and h.baseFilename == str(main_log_file)
            for h in logger.handlers
        ):
            logger.addHandler(file_handler)


def setup_logger(
    name: str,
    level: int = LOG_LEVEL,
    log_file: Optional[Path] = None,
    colorful: bool = True,
) -> logging.Logger:
    """
    创建并配置 logger

    Args:
        name: logger 名称（通常用 __name__）
        level: 日志级别
        log_file: 日志文件路径（可选）
        colorful: 是否启用彩色输出

    Returns:
        配置好的 logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    if colorful:
        # 使用自定义formatter添加颜色
        console_handler.setFormatter(
            _ColoredFormatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT)
        )
    else:
        console_handler.setFormatter(
            logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT)
        )

    logger.addHandler(console_handler)

    # 文件 Handler
    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(file_handler)

    return logger


_all_loggers_configured = False
_all_loggers_lock = threading.Lock()


def get_logger(name: str) -> logging.Logger:
    """
    获取模块级 logger（推荐用法）

    自动配置文件日志（如果尚未配置）
    """
    global _all_loggers_configured

    logger = logging.getLogger(name)

    with _all_loggers_lock:
        if not _all_loggers_configured:
            try:
                configure_all_loggers(get_log_dir())
                _all_loggers_configured = True
            except Exception:
                pass

    return logger


class _ColoredFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


class TaskLogHandler(logging.Handler):
    """任务专用日志处理器 - 写入任务日志文件"""

    def __init__(self, task_id: str):
        super().__init__()
        self.task_id = task_id
        self.log_file = get_task_log_file(task_id)
        self._lock = threading.Lock()
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("llamaindex.kb.task"):
            try:
                msg = self.format(record)
                with self._lock:
                    with open(self.log_file, "a", encoding="utf-8") as f:
                        f.write(msg + "\n")
                        f.flush()
            except Exception:
                pass


# 预配置的常用 logger
def get_app_logger() -> logging.Logger:
    """获取应用主 logger"""
    return setup_logger("llamaindex", level=LOG_LEVEL)


def get_kb_logger() -> logging.Logger:
    """获取知识库模块 logger"""
    return setup_logger("llamaindex.kb", level=LOG_LEVEL)


def get_api_logger() -> logging.Logger:
    """获取 API 模块 logger"""
    return setup_logger("llamaindex.api", level=LOG_LEVEL)
