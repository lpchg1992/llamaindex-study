"""
Dependencies and shared utilities for the API.
Extracted from api.py to avoid circular imports.
"""

from __future__ import annotations

import asyncio
import asyncio
import markdown
import threading
from typing import Optional

from fastapi import FastAPI
from contextlib import asynccontextmanager


# ============== Global Event Loop ==============

_task_loop: Optional[asyncio.AbstractEventLoop] = None
_task_thread: Optional[threading.Thread] = None


def _get_or_create_loop():
    """获取或创建事件循环"""
    global _task_loop, _task_thread

    if _task_loop is None or _task_loop.is_closed():
        _task_loop = asyncio.new_event_loop()
        _task_thread = threading.Thread(
            target=_run_loop, args=(_task_loop,), daemon=True
        )
        _task_thread.start()

    return _task_loop


def _run_loop(loop):
    """运行事件循环"""
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        loop.close()


# ============== Lifespan ==============


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    from rag.logger import get_logger

    logger = get_logger(__name__)
    logger.info("应用启动中...")

    from rag.callbacks import setup_callbacks
    from rag.token_stats_db import init_token_stats_db

    setup_callbacks()
    init_token_stats_db()
    logger.info("Token 监控已初始化")

    logger.info("应用启动完成")
    yield
    logger.info("应用关闭")


# ============== CORS Configuration ==============


def get_cors_origins() -> list:
    """Get allowed CORS origins."""
    return [
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:37241",
        "http://localhost:37241",
        # 远程 LAN 访问
        "http://100.66.1.2:5173",
        "http://100.66.1.2:37241",
        # 用户 LAN 访问
        "http://192.168.31.207:5173",
        "http://192.168.31.207:37241",
    ]


# ============== API Documentation Renderer ==============


def render_markdown_to_html(md_content: str, title: str = "") -> str:
    """Convert markdown to HTML with syntax highlighting."""
    html_content = markdown.markdown(
        md_content,
        extensions=["tables", "fenced_code", "codehilite"],
    )
    return f"""
    <div class="content">
        {html_content}
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
    """


def get_common_styles() -> str:
    """Get common CSS styles for API docs."""
    return """
        :root {
            --bg-color: #ffffff;
            --text-color: #333333;
            --code-bg: #f5f5f5;
            --border-color: #dddddd;
            --link-color: #0066cc;
            --header-bg: #2c3e50;
            --header-color: #ffffff;
            --table-header-bg: #f0f0f0;
            --blockquote-border: #4caf50;
            --sidebar-bg: #f8f9fa;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --bg-color: #1a1a1a;
                --text-color: #e0e0e0;
                --code-bg: #2d2d2d;
                --border-color: #404040;
                --link-color: #66b3ff;
                --header-bg: #2c3e50;
                --table-header-bg: #2d2d2d;
                --sidebar-bg: #252525;
            }
        }
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            background-color: var(--bg-color);
            color: var(--text-color);
        }
        .layout {
            display: flex;
            min-height: 100vh;
        }
        .sidebar {
            width: 280px;
            background-color: var(--sidebar-bg);
            border-right: 1px solid var(--border-color);
            padding: 20px;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
        }
        .main {
            flex: 1;
            padding: 20px 40px;
            max-width: 1100px;
            margin-left: 280px;
        }
        h1, h2, h3, h4 { margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 600; }
        h1 { font-size: 2.2em; border-bottom: 3px solid var(--header-bg); padding-bottom: 0.3em; }
        h2 { font-size: 1.8em; border-bottom: 1px solid var(--border-color); padding-bottom: 0.2em; }
        a { color: var(--link-color); text-decoration: none; }
        a:hover { text-decoration: underline; }
        code {
            background-color: var(--code-bg);
            padding: 2px 6px;
            border-radius: 3px;
            font-family: "SF Mono", Monaco, Consolas, monospace;
            font-size: 0.9em;
        }
        pre {
            background-color: var(--code-bg);
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
            border: 1px solid var(--border-color);
        }
        pre code { padding: 0; background: none; }
        table { width: 100%; border-collapse: collapse; margin: 1em 0; }
        th, td { border: 1px solid var(--border-color); padding: 10px 12px; text-align: left; }
        th { background-color: var(--table-header-bg); font-weight: 600; }
        blockquote {
            margin: 1em 0;
            padding: 0.5em 1em;
            border-left: 4px solid var(--blockquote-border);
            background-color: var(--code-bg);
        }
        .nav {
            background-color: var(--header-bg);
            color: var(--header-color);
            padding: 15px 20px;
        }
        .nav a { color: var(--header-color); margin-right: 20px; }
        .nav a:hover { text-decoration: underline; }
        .doc-card {
            background: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 15px;
            transition: box-shadow 0.2s;
        }
        .doc-card:hover {
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        .doc-card h3 { margin: 0 0 10px 0; }
        .doc-card p { margin: 0; color: #666; }
        .doc-card .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            margin-right: 8px;
        }
        .badge-api { background: #e3f2fd; color: #1565c0; }
        .badge-cli { background: #e8f5e9; color: #2e7d32; }
        .badge-arch { background: #fff3e0; color: #e65100; }
        .badge-guide { background: #f3e5f5; color: #7b1fa2; }
        .active-doc { font-weight: bold; color: var(--link-color); }
        @media (max-width: 768px) {
            .sidebar { display: none; }
            .main { margin-left: 0; padding: 20px; }
        }
    """


def get_common_head() -> str:
    """Get common HTML head content."""
    return f"""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/default.min.css">
    <style>{get_common_styles()}</style>
    """


def get_sidebar_html(
    api_active: str = "",
    cli_active: str = "",
    arch_active: str = "",
    guide_active: str = "",
    search_active: str = "",
) -> str:
    """Get sidebar HTML with navigation."""
    return f"""
    <div class="sidebar">
        <h3 style="margin-top: 0;">📚 文档中心</h3>
        <ul style="list-style: none; padding: 0;">
            <li style="margin-bottom: 8px;">
                <a href="/api-docs" {api_active}>📖 API 文档</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=CLI" {cli_active}>💻 CLI 使用指南</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=ARCHITECTURE" {arch_active}>🏗️ 架构设计</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=QUERY_PARAM_GUIDE" {guide_active}>🎯 Query 参数指南</a>
            </li>
            <li style="margin-bottom: 8px;">
                <a href="/api-docs?doc=SEARCH_PARAM_GUIDE" {search_active}>🔍 Search 参数指南</a>
            </li>
        </ul>
        <hr style="margin: 20px 0; border: none; border-top: 1px solid var(--border-color);">
        <h4>快速链接</h4>
        <ul style="list-style: none; padding: 0; font-size: 0.9em;">
            <li style="margin-bottom: 6px;">📄 <a href="/api-docs?doc=API#检索查询">检索查询 API</a></li>
            <li style="margin-bottom: 6px;">📥 <a href="/api-docs?doc=API#文档导入">文档导入 API</a></li>
            <li style="margin-bottom: 6px;">⚡ <a href="/api-docs?doc=API#任务队列">任务队列 API</a></li>
        </ul>
    </div>
    """


def get_doc_files() -> dict:
    """Get mapping of doc names to file names."""
    return {
        "API": "API.md",
        "CLI": "CLI.md",
        "ARCHITECTURE": "ARCHITECTURE.md",
        "QUERY_PARAM_GUIDE": "QUERY_PARAM_GUIDE.md",
        "SEARCH_PARAM_GUIDE": "SEARCH_PARAM_GUIDE.md",
    }