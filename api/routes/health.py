"""
Health check and API documentation endpoints.
"""

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from api.deps import (
    get_common_head,
    get_sidebar_html,
    get_doc_files,
    render_markdown_to_html,
)

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    from rag import __version__
    return {
        "status": "ok",
        "service": "llamaindex-rag-api",
        "version": __version__,
    }


@router.get("/api-docs", response_class=HTMLResponse)
def api_docs_page(doc: str = Query(None)):
    from pathlib import Path
    import markdown

    docs_dir = Path(__file__).parent.parent.parent / "docs"

    doc_files = get_doc_files()

    if doc is None:
        doc_content = """
        <h1>📚 LlamaIndex RAG 文档中心</h1>
        <p style="font-size: 1.1em; color: #666;">欢迎使用 LlamaIndex RAG 文档中心。这里提供了所有相关文档的链接。</p>

        <div class="doc-card">
            <span class="badge badge-api">API</span>
            <h3><a href="/api-docs?doc=API">API 完整参考</a></h3>
            <p>FastAPI 所有端点的详细说明，包括请求参数、响应格式、示例。</p>
        </div>

        <div class="doc-card">
            <span class="badge badge-guide">🎯 必读</span>
            <h3><a href="/api-docs?doc=QUERY_PARAM_GUIDE">Query 参数设计指南</a></h3>
            <p>客户端 UI 设计必读！详细说明 route_mode、retrieval_mode 及各检索增强参数的适用场景和组合建议。</p>
        </div>

        <div class="doc-card">
            <span class="badge badge-guide">🔍 必读</span>
            <h3><a href="/api-docs?doc=SEARCH_PARAM_GUIDE">Search 参数设计指南</a></h3>
            <p>Search 检索的专用指南，说明检索模式、结果排序等参数。</p>
        </div>

        <div class="doc-card">
            <span class="badge badge-cli">CLI</span>
            <h3><a href="/api-docs?doc=CLI">CLI 使用指南</a></h3>
            <p>完整的命令行接口文档，包括知识库管理、文档导入、检索查询、任务管理等命令。</p>
        </div>

        <div class="doc-card">
            <span class="badge badge-arch">架构</span>
            <h3><a href="/api-docs?doc=ARCHITECTURE">架构设计文档</a></h3>
            <p>系统架构、分层设计、并行处理、资源保护机制、数据库 Schema 等技术细节。</p>
        </div>
        """
        content_html = f"""
        <div class="layout">
            {get_sidebar_html()}
            <div class="main">
                {doc_content}
            </div>
        </div>
        """
    elif doc in doc_files:
        docs_path = docs_dir / doc_files[doc]
        if docs_path.exists():
            md_content = docs_path.read_text(encoding="utf-8")
            content_html = render_markdown_to_html(md_content, doc)

            active_states = {
                "api_active": "",
                "cli_active": "",
                "arch_active": "",
                "guide_active": "",
                "search_active": "",
            }
            if doc == "API":
                active_states["api_active"] = 'class="active-doc"'
            elif doc == "CLI":
                active_states["cli_active"] = 'class="active-doc"'
            elif doc == "ARCHITECTURE":
                active_states["arch_active"] = 'class="active-doc"'
            elif doc == "QUERY_PARAM_GUIDE":
                active_states["guide_active"] = 'class="active-doc"'
            elif doc == "SEARCH_PARAM_GUIDE":
                active_states["search_active"] = 'class="active-doc"'

            content_html = f"""
            <div class="layout">
                {get_sidebar_html(**active_states)}
                <div class="main">
                    {content_html}
                </div>
            </div>
            """
        else:
            content_html = f"<h1>文档未找到</h1><p>{doc_files[doc]} 不存在</p>"
    else:
        content_html = f"<h1>文档未找到</h1><p>未知的文档: {doc}</p>"

    html_page = f"""<!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>文档中心 - LlamaIndex RAG API</title>
        {get_common_head()}
    </head>
    <body>
        {content_html}
    </body>
    </html>"""
    return html_page