"""
日志工具模块

提供统一的日志配置，支持：
- 控制台彩色输出（开发友好）
- 文件日志（持久化记录）
- 模块级 logger 获取
"""

import logging
import sys
from pathlib import Path
from typing import Optional


# 日志格式
CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
DATE_FORMAT = "%H:%M:%S"

# 日志级别
LOG_LEVEL = logging.INFO


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
        console_handler.setFormatter(_ColoredFormatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT))
    else:
        console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT))
    
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


def get_logger(name: str) -> logging.Logger:
    """
    获取模块级 logger（推荐用法）
    
    用法：
        from llamaindex_study.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Hello")
    """
    return logging.getLogger(name)


class _ColoredFormatter(logging.Formatter):
    """彩色日志格式化器"""
    
    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


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
