#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kb.services import (
    AdminService,
    CategoryService,
    KnowledgeBaseService,
    ObsidianService,
    SearchService,
    TaskService,
    ZoteroService,
)
from llamaindex_study.config import get_settings
from llamaindex_study.index_builder import IndexBuilder
from llamaindex_study.query_engine import QueryEngineWrapper
from llamaindex_study.reader import DocumentReader


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def get_query_from_args_or_stdin(args: argparse.Namespace) -> Optional[str]:
    query = getattr(args, "query", None)
    if query:
        if isinstance(query, list):
            query = " ".join(query)
        if query.strip():
            return query.strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return None


def print_table(rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    rows = list(rows)
    if not rows:
        print("无数据")
        return

    widths = {col: len(col) for col in columns}
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = {}
        for col in columns:
            value = row.get(col, "")
            if isinstance(value, (dict, list)):
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = str(value)
            normalized[col] = text
            widths[col] = max(widths[col], len(text))
        normalized_rows.append(normalized)

    header = "  ".join(col.ljust(widths[col]) for col in columns)
    print(header)
    print("  ".join("-" * widths[col] for col in columns))
    for row in normalized_rows:
        print("  ".join(row[col].ljust(widths[col]) for col in columns))


def coerce_param_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def parse_key_values(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"参数格式错误: {item}，应为 key=value")
        key, value = item.split("=", 1)
        result[key] = coerce_param_value(value)
    return result


def print_welcome() -> None:
    from kb.services import KnowledgeBaseService

    kbs = KnowledgeBaseService.list_all()

    print("\n" + "=" * 60)
    print("🤖 LlamaIndex Study - 交互式查询系统")
    print("=" * 60)
    print("\n📚 可用知识库：")
    if kbs:
        for kb in kbs:
            print(f"  • {kb['id']:20s} - {kb['name']} ({kb['row_count']} 条)")
    else:
        print("  （暂无可用知识库）")
    print("\n命令提示：")
    print("  - 直接输入问题 → 自动选择知识库进行 RAG 问答")
    print("  - /search <kb_id> <query> → 指定知识库检索")
    print("  - /query <kb_id> <question> → 指定知识库问答")
    print("  - /list → 显示知识库列表")
    print("  - /exclude <kb1,kb2,...> → 设置排除的知识库")
    print("  - /excludes → 查看当前排除设置")
    print("  - /auto → 切换自动/手动选择知识库")
    print("  - stream → 切换流式/普通模式")
    print("  - quit/exit → 退出")
    print("=" * 60 + "\n")


def load_documents(data_dir: Path) -> list:
    print(f"📂 正在加载文档: {data_dir}")
    reader = DocumentReader(
        input_dir=data_dir,
        required_exts=[".txt", ".md"],
    )
    documents = reader.load()
    print(f"✅ 成功加载 {len(documents)} 个文档\n")
    return documents


def run_interactive() -> int:
    from kb.services import KnowledgeBaseService, QueryRouter, SearchService

    settings = get_settings()
    print(f"🔧 使用配置: {settings}")
    print(f"   LLM: SiliconFlow ({settings.siliconflow_model})")
    print(f"   Embedding: Ollama ({settings.ollama_embed_model})")

    kbs = KnowledgeBaseService.list_all()
    print(f"📚 已加载 {len(kbs)} 个知识库")

    print_welcome()

    stream_mode = False
    auto_mode = True
    exclude_kbs: Optional[List[str]] = None
    while True:
        try:
            user_input = input("💬 你: ").strip()

            if user_input.lower() in ["quit", "exit", "q"]:
                print("\n👋 再见！感谢使用 LlamaIndex Study。")
                return 0

            if user_input.lower() == "stream":
                stream_mode = not stream_mode
                status = "开启" if stream_mode else "关闭"
                print(f"🔄 流式输出已{status}\n")
                continue

            if user_input.lower() == "/list":
                kbs = KnowledgeBaseService.list_all()
                print("\n📚 可用知识库：")
                for kb in kbs:
                    print(f"  • {kb['id']:20s} - {kb['name']} ({kb['row_count']} 条)")
                print()
                continue

            if user_input.lower() == "/auto":
                auto_mode = not auto_mode
                status = "开启" if auto_mode else "关闭"
                print(f"🔄 自动选择知识库已{status}\n")
                continue

            if user_input.lower().startswith("/exclude "):
                exclude_str = user_input[9:].strip()
                if exclude_str:
                    exclude_kbs = [
                        e.strip() for e in exclude_str.split(",") if e.strip()
                    ]
                    print(f"🚫 已设置排除知识库: {', '.join(exclude_kbs)}\n")
                else:
                    exclude_kbs = None
                    print("✅ 已清除排除设置\n")
                continue

            if user_input.lower() == "/excludes":
                if exclude_kbs:
                    print(f"🚫 当前排除: {', '.join(exclude_kbs)}\n")
                else:
                    print("✅ 当前无排除设置\n")
                continue

            if user_input.lower().startswith("/search "):
                parts = user_input[8:].strip().split(" ", 1)
                if len(parts) == 2:
                    kb_id, query = parts
                    print(f"\n🔍 在知识库 [{kb_id}] 中检索...")
                    results = SearchService.search(kb_id, query, top_k=5)
                    print(f"📊 找到 {len(results)} 条结果：\n")
                    for i, r in enumerate(results, 1):
                        print(f"  [{i}] (score: {r.get('score', 0):.2f})")
                        print(f"      {r['text'][:200]}...")
                        print()
                else:
                    print("❌ 格式: /search <kb_id> <query>\n")
                continue

            if user_input.lower().startswith("/query "):
                parts = user_input[7:].strip().split(" ", 1)
                if len(parts) == 2:
                    kb_id, question = parts
                    print(f"\n🤖 在知识库 [{kb_id}] 中问答...")
                    result = SearchService.query(kb_id, question, top_k=5)
                    print(f"\n💬 回答：\n{result['response']}\n")
                else:
                    print("❌ 格式: /query <kb_id> <question>\n")
                continue

            if not user_input:
                continue

            if auto_mode:
                print(f"\n🤖 AI: (自动路由中...)\n")
                result = QueryRouter.query(user_input, top_k=5, exclude=exclude_kbs)
                print(f"📊 查询了: {', '.join(result.get('kbs_queried', []))}\n")
                print(f"💬 回答：\n{result['response']}\n")
            else:
                print("❌ 请先选择一个知识库，或输入 /auto 开启自动选择\n")

        except KeyboardInterrupt:
            print("\n\n👋 再见！")
            return 0
        except Exception as e:
            print(f"\n❌ 发生错误: {e}\n")


def submit_task_and_handle(
    task_type: str, kb_id: str, params: dict[str, Any], source: str
) -> int:
    from kb.task_executor import SchedulerStarter, is_scheduler_running

    # 检查并自动启动 scheduler
    if not is_scheduler_running():
        print("⚙️  调度器未运行，正在启动...", file=sys.stderr)
        SchedulerStarter.ensure_scheduler_running()

    result = TaskService.submit(
        task_type=task_type, kb_id=kb_id, params=params, source=source
    )
    print_json(result)

    return 0


def handle_kb_list(_: argparse.Namespace) -> int:
    print_table(
        KnowledgeBaseService.list_all(),
        ["id", "name", "status", "row_count", "description"],
    )
    return 0


def handle_kb_show(args: argparse.Namespace) -> int:
    info = KnowledgeBaseService.get_info(args.kb_id)
    if info is None:
        raise ValueError(f"知识库不存在: {args.kb_id}")
    print_json(info)
    return 0


def handle_kb_create(args: argparse.Namespace) -> int:
    result = KnowledgeBaseService.create(args.kb_id, args.name, args.description)
    print_json(result)
    return 0


def handle_kb_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("删除知识库需要显式传入 --yes")
    success = KnowledgeBaseService.delete(args.kb_id)
    print_json({"kb_id": args.kb_id, "deleted": success})
    return 0


def handle_kb_initialize(args: argparse.Namespace) -> int:
    return submit_task_and_handle(
        "initialize", args.kb_id, {}, source="cli:kb:initialize"
    )


def handle_kb_topics(args: argparse.Namespace) -> int:
    from kb.topic_analyzer import analyze_and_update_topics
    from kb.registry import registry
    from kb.database import init_kb_meta_db

    if args.all:
        kb_ids = [kb.id for kb in registry.list_all()]
    elif args.kb_id:
        kb_ids = [args.kb_id]
    else:
        print("错误: 请指定 kb_id 或使用 --all", file=sys.stderr)
        return 1

    for kb_id in kb_ids:
        print(f"\n分析知识库: {kb_id}")
        topics = analyze_and_update_topics(kb_id, has_new_docs=True)
        if topics:
            print(f"  主题词 ({len(topics)} 个):")
            for t in topics[:15]:
                print(f"    - {t}")
            if len(topics) > 15:
                print(f"    ... 共 {len(topics)} 个")
        else:
            print(f"  无主题词")
        if args.update:
            db = init_kb_meta_db()
            db.update_topics(kb_id, topics)
            print(f"  已更新到数据库")

    return 0


def handle_kb_topics_local(args: argparse.Namespace) -> int:
    import httpx
    import re
    from collections import Counter
    from kb.registry import registry

    OLLAMA_URL = "http://localhost:11434/api/chat"
    LOCAL_MODEL = "tomng/lfm2.5-instruct:1.2b"

    EXTRACT_PROMPT = """你是一个专业的知识库主题分析助手。请从以下文档内容中提取3-8个主题词。
    要求：
    1. 只提取专业术语、学术名词、具体概念
    2. 只提取名词性词汇，不要动词、形容词
    3. 用换行符分隔，每行一个词

    ---文档内容---
    {text}
    ---文档结束---

    主题词（每行一个）："""

    REVIEW_PROMPT = """以下是从知识库文档中提取的主题词。请审查并过滤掉：
    1. 过于通用的词（如"实验设计"、"专业术语"、"使用者"、"注意事项"）
    2. 疑似幻觉/错误的词
    3. 动词、形容词、副词
    4. 长度小于2的词

    保留真正有学科特色的专业术语。

    主题词列表：
    {keywords}

    过滤后的有效主题词（每行一个，只返回有效的）："""

    client = httpx.Client(timeout=60.0)

    def wait_for_model_ready(max_wait=120):
        start = time.time()
        while time.time() - start < max_wait:
            try:
                resp = client.get(f"{OLLAMA_URL.rsplit('/api/', 1)[0]}/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])]
                    if LOCAL_MODEL in models:
                        return True
            except:
                pass
            time.sleep(1)
        return False

    def extract_with_retry(text, max_retries=3):
        prompt = EXTRACT_PROMPT.format(text=text[:2000])
        for attempt in range(max_retries):
            try:
                resp = client.post(
                    OLLAMA_URL,
                    json={
                        "model": LOCAL_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    result = resp.json().get("message", {}).get("content", "")
                    keywords = []
                    for line in result.split("\n"):
                        line = line.strip().strip("0123456789.-、，、:：) ")
                        if line and len(line) >= 2:
                            keywords.append(line)
                    return keywords
                elif resp.status_code == 503:
                    print(f"  [模型加载中，重试 {attempt + 1}/{max_retries}]")
                    time.sleep(2)
                else:
                    return []
            except Exception as e:
                if attempt == max_retries - 1:
                    return []
        return []

    def _is_garbage(kw):
        if not kw or len(kw) < 2:
            return True
        junk = {
            "iss",
            "thr",
            "com",
            "www",
            "http",
            "https",
            "ftp",
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "has",
            "his",
            "how",
            "its",
            "may",
            "new",
            "now",
            "old",
            "see",
            "two",
            "way",
            "who",
            "boy",
            "did",
            "get",
            "let",
            "put",
            "say",
            "she",
            "too",
            "use",
            "dir",
            "lst",
            "idx",
            "tmp",
            "bak",
            "ddd",
            "mmm",
            "yyy",
            "xxx",
            "www",
            "png",
            "jpg",
            "gif",
            "css",
            "js",
            "html",
            "xml",
            "json",
            "实验设计",
            "专业术语",
            "使用者",
            "注意事项",
        }
        if kw.lower() in junk:
            return True
        if re.match(r"^\d+$", kw):
            return True
        if re.match(r"^[a-zA-Z]{1,2}$", kw):
            return True
        return False

    def _is_similar(kw1, kw2):
        if kw1.lower() == kw2.lower():
            return True
        particles = {"的", "之", "于", "在", "和", "与", "及"}
        rp1 = "".join(c for c in kw1 if c not in particles)
        rp2 = "".join(c for c in kw2 if c not in particles)
        if rp1 and rp2:
            if rp1 in rp2 or rp2 in rp1:
                return True
        n = 2
        ngrams1 = (
            set(kw1[i : i + n] for i in range(len(kw1) - n + 1))
            if len(kw1) >= n
            else {kw1}
        )
        ngrams2 = (
            set(kw2[i : i + n] for i in range(len(kw2) - n + 1))
            if len(kw2) >= n
            else {kw2}
        )
        if not ngrams1 or not ngrams2:
            return False
        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)
        return (intersection / union) >= 0.75 if union > 0 else False

    def review_keywords(keywords):
        if not keywords:
            return []
        prompt = REVIEW_PROMPT.format(keywords="\n".join(keywords))
        try:
            resp = client.post(
                OLLAMA_URL,
                json={
                    "model": LOCAL_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            result = resp.json().get("message", {}).get("content", "")
            reviewed = []
            for line in result.split("\n"):
                line = line.strip().strip("0123456789.-、，、:：) ")
                if line and len(line) >= 2:
                    reviewed.append(line)
            return reviewed
        except Exception as e:
            print(f"  [警告] 审查失败: {e}")
            return keywords

    def local_rule_filter(keywords):
        result = []
        for kw in keywords:
            if _is_garbage(kw):
                continue
            is_dup = False
            for existing in result:
                if _is_similar(kw, existing):
                    is_dup = True
                    break
            if not is_dup:
                result.append(kw)
        return result

    def get_chunks(kb_id):
        kb = registry.get(kb_id)
        if not kb:
            return []
        persist_dir = kb.persist_dir
        if not persist_dir.exists():
            return []
        try:
            import lancedb

            db = lancedb.connect(str(persist_dir))
            table = db.open_table(db.table_names()[0])
            df = table.to_pandas()
            return df["text"].dropna().tolist() if "text" in df.columns else []
        except:
            return []

    if args.all:
        kb_ids = [kb.id for kb in registry.list_all()]
    elif args.kb_id:
        kb_ids = [args.kb_id]
    else:
        print("错误: 请指定 kb_id 或使用 --all", file=sys.stderr)
        return 1

    for kb_id in kb_ids:
        print(f"\n{'=' * 50}")
        print(f"处理知识库: {kb_id}")
        chunks = get_chunks(kb_id)
        if not chunks:
            print(f"  无文档")
            continue
        print(f"  共 {len(chunks)} 个 chunks（全部处理）")

        print(f"  [等待模型就绪...]")
        if not wait_for_model_ready():
            print(f"  [警告] 模型未就绪，继续尝试...")
        else:
            print(f"  [模型已就绪]")

        print(f"  [阶段1] 提取主题词...")
        all_keywords = []
        for i, chunk in enumerate(chunks):
            if len(chunk) < 50:
                continue
            keywords = extract_with_retry(chunk)
            if keywords:
                all_keywords.append(keywords)
            if (i + 1) % 50 == 0:
                print(f"    已处理 {i + 1}/{len(chunks)}")

        if not all_keywords:
            print(f"  未能提取主题词")
            continue

        print(f"  [阶段2] 本地规则过滤...")
        counter = Counter()
        for keywords in all_keywords:
            for kw in keywords:
                if not _is_garbage(kw):
                    counter[kw] += 1
        merged = [kw for kw, _ in counter.most_common(80)]
        filtered = local_rule_filter(merged)
        print(f"  规则过滤后: {len(filtered)} 个")

        print(f"  [阶段3] 本地模型二次审查...")
        reviewed = review_keywords(filtered)
        if reviewed:
            filtered = reviewed
            print(f"  审查后: {len(filtered)} 个")
        else:
            print(f"  审查失败，保留原结果")

        print(f"\n  最终主题词 ({len(filtered)} 个):")
        for kw in filtered[:20]:
            print(f"    - {kw}")
        if len(filtered) > 20:
            print(f"    ... 共 {len(filtered)} 个")

        if args.update:
            from kb.database import init_kb_meta_db

            db = init_kb_meta_db()
            db.update_topics(kb_id, filtered)
            print(f"\n  已更新到数据库")

    print(f"\n{'=' * 50}")
    print("完成!")
    return 0


def handle_search(args: argparse.Namespace) -> int:
    query = get_query_from_args_or_stdin(args)
    if not query:
        print("错误: 请提供查询内容", file=sys.stderr)
        return 1

    use_auto_merging = getattr(args, "auto_merging", False)
    kb_ids = getattr(args, "kb_ids", None)

    if kb_ids:
        kb_id_list = [k.strip() for k in kb_ids.split(",") if k.strip()]
        if len(kb_id_list) == 1:
            result = SearchService.search(
                kb_id_list[0],
                query,
                top_k=args.top_k,
                use_auto_merging=use_auto_merging,
            )
        else:
            result = SearchService.search_multi(
                kb_id_list,
                query,
                top_k=args.top_k,
                use_auto_merging=use_auto_merging,
            )
    elif getattr(args, "auto", False):
        from kb.services import QueryRouter

        exclude = getattr(args, "exclude", None)
        if exclude:
            exclude = [e.strip() for e in exclude.split(",") if e.strip()]
        result = QueryRouter.search(
            query,
            top_k=args.top_k,
            exclude=exclude,
            use_auto_merging=use_auto_merging,
        )
    else:
        result = SearchService.search(
            args.kb_id,
            query,
            top_k=args.top_k,
            use_auto_merging=use_auto_merging,
        )
    print_json(result)
    return 0


def handle_query(args: argparse.Namespace) -> int:
    query = get_query_from_args_or_stdin(args)
    if not query:
        print("错误: 请提供查询内容", file=sys.stderr)
        return 1

    kb_ids = getattr(args, "kb_ids", None)
    use_hyde = getattr(args, "use_hyde", None)
    use_multi_query = getattr(args, "use_multi_query", None)
    use_auto_merging = getattr(args, "use_auto_merging", None)
    response_mode = getattr(args, "response_mode", None)

    if kb_ids:
        kb_id_list = [k.strip() for k in kb_ids.split(",") if k.strip()]
        if len(kb_id_list) == 1:
            result = SearchService.query(
                kb_id_list[0],
                query,
                top_k=args.top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                use_auto_merging=use_auto_merging,
                response_mode=response_mode,
            )
        else:
            from kb.services import QueryRouter

            result = QueryRouter.query_multi(
                kb_id_list,
                query,
                top_k=args.top_k,
                use_hyde=use_hyde,
                use_multi_query=use_multi_query,
                use_auto_merging=use_auto_merging,
                response_mode=response_mode,
            )
    elif getattr(args, "auto", False):
        from kb.services import QueryRouter

        exclude = getattr(args, "exclude", None)
        if exclude:
            exclude = [e.strip() for e in exclude.split(",") if e.strip()]
        result = QueryRouter.query(
            query,
            top_k=args.top_k,
            exclude=exclude,
            use_hyde=use_hyde,
            use_multi_query=use_multi_query,
            use_auto_merging=use_auto_merging,
            response_mode=response_mode,
        )
    else:
        result = SearchService.query(
            args.kb_id,
            query,
            top_k=args.top_k,
            use_hyde=use_hyde,
            use_multi_query=use_multi_query,
            use_auto_merging=use_auto_merging,
            response_mode=response_mode,
        )
    print_json(result)
    return 0


def handle_ingest_obsidian(args: argparse.Namespace) -> int:
    params = {
        "vault_path": args.vault_path,
        "folder_path": args.folder_path,
        "recursive": args.recursive,
        "rebuild": args.rebuild,
        "force_delete": args.force_delete,
        "persist_dir": args.persist_dir,
    }
    return submit_task_and_handle(
        "obsidian",
        args.kb_id,
        params,
        source=args.folder_path or args.vault_path,
    )


def handle_ingest_zotero(args: argparse.Namespace) -> int:
    params = {
        "collection_id": args.collection_id,
        "collection_name": args.collection_name,
        "rebuild": args.rebuild,
    }
    source = args.collection_name or args.collection_id or "zotero"
    return submit_task_and_handle("zotero", args.kb_id, params, source=source)


def _collect_files_for_validation(
    paths: List[str],
    include_exts: List[str] = None,
    exclude_exts: List[str] = None,
) -> tuple[int, List[str]]:
    from kb.generic_processor import GenericImporter

    importer = GenericImporter()
    all_files: List[Path] = []
    warnings: List[str] = []

    for path_str in paths:
        p = Path(path_str)
        if not p.exists():
            warnings.append(f"路径不存在: {path_str}")
            continue

        if p.is_file():
            all_files.append(p)
        elif p.is_dir():
            files = importer.collect_files(
                [p],
                recursive=True,
                include_exts=include_exts,
                exclude_exts=exclude_exts,
            )
            all_files.extend(files)

    return len(all_files), warnings


def handle_ingest_file(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.exists():
        print(f"❌ 路径不存在: {args.path}", file=sys.stderr)
        return 1

    file_count, warnings = _collect_files_for_validation([args.path])
    for w in warnings:
        print(f"⚠️  {w}", file=sys.stderr)

    if file_count == 0:
        print(f"❌ 没有找到可处理的文件: {args.path}", file=sys.stderr)
        return 1

    print(f"📁 将导入 {file_count} 个文件")
    return submit_task_and_handle(
        "generic", args.kb_id, {"paths": [args.path]}, source=args.path
    )


def handle_ingest_batch(args: argparse.Namespace) -> int:
    paths = args.paths
    include_exts = None
    exclude_exts = None

    if hasattr(args, "include") and args.include:
        include_exts = [
            ext.strip().lower().lstrip(".") for ext in args.include.split(",")
        ]

    if hasattr(args, "exclude") and args.exclude:
        exclude_exts = [
            ext.strip().lower().lstrip(".") for ext in args.exclude.split(",")
        ]

    for path_str in paths:
        p = Path(path_str)
        if not p.exists():
            print(f"❌ 路径不存在: {path_str}", file=sys.stderr)
            return 1

    file_count, warnings = _collect_files_for_validation(
        paths, include_exts, exclude_exts
    )
    for w in warnings:
        print(f"⚠️  {w}", file=sys.stderr)

    if file_count == 0:
        print(f"❌ 没有找到可处理的文件", file=sys.stderr)
        return 1

    print(f"📁 将导入 {file_count} 个文件")
    params = {"paths": paths}
    if include_exts:
        params["include_exts"] = include_exts
    if exclude_exts:
        params["exclude_exts"] = exclude_exts

    return submit_task_and_handle(
        "generic",
        args.kb_id,
        params,
        source=paths[0],
    )


def handle_ingest_rebuild(args: argparse.Namespace) -> int:
    params = {"rebuild": True}
    return submit_task_and_handle(
        "obsidian", args.kb_id, params, source="cli:ingest:rebuild"
    )


def handle_obsidian_vaults(_: argparse.Namespace) -> int:
    print_json(ObsidianService.get_vaults())
    return 0


def handle_obsidian_info(args: argparse.Namespace) -> int:
    info = ObsidianService.get_vault_info(args.vault_name)
    if not info:
        raise ValueError(f"Vault 不存在: {args.vault_name}")
    print_json(info)
    return 0


def handle_obsidian_mappings(_: argparse.Namespace) -> int:
    from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS

    rows = [
        {
            "kb_id": mapping.kb_id,
            "name": mapping.name,
            "folders": ", ".join(mapping.folders),
        }
        for mapping in OBSIDIAN_KB_MAPPINGS
    ]
    print_table(rows, ["kb_id", "name", "folders"])
    return 0


def handle_obsidian_import_all(args: argparse.Namespace) -> int:
    from kb.obsidian_config import OBSIDIAN_KB_MAPPINGS

    results = []
    for mapping in OBSIDIAN_KB_MAPPINGS:
        folders = mapping.folders or [None]
        for folder_path in folders:
            submission = TaskService.submit(
                task_type="obsidian",
                kb_id=mapping.kb_id,
                params={
                    "vault_path": args.vault_path,
                    "folder_path": folder_path,
                    "recursive": True,
                    "rebuild": args.rebuild,
                    "force_delete": args.force_delete,
                },
                source=folder_path or mapping.kb_id,
            )
            results.append(submission)
    print_json({"tasks": results, "count": len(results)})
    return 0


def handle_zotero_collections(args: argparse.Namespace) -> int:
    result = ZoteroService.list_collections()
    if args.limit > 0:
        result = result[: args.limit]
    print_json(result)
    return 0


def handle_zotero_search(args: argparse.Namespace) -> int:
    result = ZoteroService.search_collections(args.keyword)
    print_json(result)
    return 0


def handle_task_submit(args: argparse.Namespace) -> int:
    params = parse_key_values(args.param or [])
    return submit_task_and_handle(
        args.task_type, args.kb_id, params, source=args.source or ""
    )


def handle_task_list(args: argparse.Namespace) -> int:
    tasks = TaskService.list_tasks(
        kb_id=args.kb_id, status=args.status, limit=args.limit
    )
    print_table(
        tasks, ["task_id", "task_type", "kb_id", "status", "progress", "message"]
    )
    return 0


def handle_task_show(args: argparse.Namespace) -> int:
    task = TaskService.get_task(args.task_id)
    if task is None:
        raise ValueError(f"任务不存在: {args.task_id}")
    print_json(task)
    return 0


def handle_task_cancel(args: argparse.Namespace) -> int:
    print_json(TaskService.cancel(args.task_id))
    return 0


def handle_task_pause(args: argparse.Namespace) -> int:
    print_json(TaskService.pause(args.task_id))
    return 0


def handle_task_pause_all(args: argparse.Namespace) -> int:
    results = TaskService.pause_all(args.status)
    print_json(results)
    return 0


def handle_task_resume(args: argparse.Namespace) -> int:
    print_json(TaskService.resume(args.task_id))
    return 0


def handle_task_resume_all(args: argparse.Namespace) -> int:
    results = TaskService.resume_all()
    print_json(results)
    return 0


def handle_task_delete(args: argparse.Namespace) -> int:
    print_json(TaskService.delete(args.task_id, cleanup=args.cleanup))
    return 0


def handle_task_delete_all(args: argparse.Namespace) -> int:
    results = TaskService.delete_all(args.status, cleanup=args.cleanup)
    print_json(results)
    return 0


def handle_task_cleanup(args: argparse.Namespace) -> int:
    results = TaskService.cleanup_orphan_tasks(cleanup=not args.no_cleanup)
    print_json(results)
    return 0


def handle_task_watch(args: argparse.Namespace) -> int:
    start = time.time()
    last_snapshot = None
    while True:
        task = TaskService.get_task(args.task_id)
        if task is None:
            raise ValueError(f"任务不存在: {args.task_id}")
        snapshot = (task["status"], task.get("progress"), task.get("message"))
        if snapshot != last_snapshot:
            print_json(task)
            last_snapshot = snapshot
        if task["status"] in {"completed", "failed", "cancelled"}:
            return 0
        if args.timeout > 0 and time.time() - start >= args.timeout:
            return 0
        time.sleep(args.interval)


def handle_category_rules_list(_: argparse.Namespace) -> int:
    result = CategoryService.list_rules()
    print_table(
        result["rules"], ["kb_id", "rule_type", "pattern", "priority", "description"]
    )
    return 0


def handle_category_rules_sync(_: argparse.Namespace) -> int:
    print_json(CategoryService.sync_rules())
    return 0


def handle_category_rules_add(args: argparse.Namespace) -> int:
    print_json(
        CategoryService.add_rule(
            kb_id=args.kb_id,
            rule_type=args.rule_type,
            pattern=args.pattern,
            description=args.description,
            priority=args.priority,
        )
    )
    return 0


def handle_category_rules_delete(args: argparse.Namespace) -> int:
    print_json(CategoryService.delete_rule(args.kb_id, args.rule_type, args.pattern))
    return 0


def handle_category_classify(args: argparse.Namespace) -> int:
    print_json(
        CategoryService.classify(
            folder_path=args.folder_path,
            folder_description=args.description,
            use_llm=args.use_llm,
        )
    )
    return 0


def handle_admin_tables(_: argparse.Namespace) -> int:
    print_table(
        AdminService.list_tables()["tables"], ["kb_id", "status", "row_count", "path"]
    )
    return 0


def handle_admin_table(args: argparse.Namespace) -> int:
    info = AdminService.get_table_info(args.kb_id)
    if info is None:
        raise ValueError(f"知识库不存在: {args.kb_id}")
    print_json(info)
    return 0


def handle_admin_delete(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ValueError("删除向量表需要显式传入 --yes")
    print_json({"kb_id": args.kb_id, "deleted": AdminService.delete_table(args.kb_id)})
    return 0


CONFIG_OPTION_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "SILICONFLOW_API_KEY": ("LLM", "硅基流动 API 密钥"),
    "SILICONFLOW_BASE_URL": ("LLM", "硅基流动 API 地址"),
    "SILICONFLOW_MODEL": ("LLM", "LLM 模型名称"),
    "OLLAMA_EMBED_MODEL": ("Embedding", "Embedding 模型名称"),
    "OLLAMA_BASE_URL": ("Embedding", "默认 Ollama 地址"),
    "OLLAMA_LOCAL_URL": ("Embedding", "本地 Ollama 地址"),
    "OLLAMA_REMOTE_URL": ("Embedding", "远程 Ollama 地址"),
    "OLLAMA_SHORT_TEXT_THRESHOLD": ("Embedding", "短文本优先单端点阈值"),
    "OLLAMA_FANOUT_TEXT_THRESHOLD": ("Embedding", "长文本阈值（已废弃）"),
    "MAX_RETRIES": ("Embedding", "每个端点最大重试次数"),
    "RETRY_DELAY": ("Embedding", "重试延迟（秒）"),
    "OBSIDIAN_VAULT_ROOT": ("存储", "Obsidian Vault 根目录"),
    "PERSIST_DIR": ("存储", "向量存储目录"),
    "ZOTERO_PERSIST_DIR": ("存储", "Zotero 向量存储目录"),
    "DATA_DIR": ("存储", "任务队列与项目数据库目录"),
    "TOP_K": ("检索", "每个知识库返回的结果数量"),
    "USE_SEMANTIC_CHUNKING": ("检索", "启用语义分块（需重建知识库）"),
    "USE_AUTO_MERGING": ("检索", "启用 Auto-Merging Retriever（需重建知识库）"),
    "USE_HYBRID_SEARCH": ("检索", "启用混合搜索（向量 + BM25）"),
    "HYBRID_SEARCH_ALPHA": ("检索", "混合搜索向量权重（0-1）"),
    "HYBRID_SEARCH_MODE": ("检索", "混合搜索融合模式"),
    "USE_HYDE": ("检索", "启用 HyDE 查询转换"),
    "USE_QUERY_REWRITE": ("检索", "启用 Query Rewriting"),
    "USE_MULTI_QUERY": ("检索", "启用多查询转换"),
    "RESPONSE_MODE": ("检索", "答案生成模式"),
    "RERANK_MODEL": ("Reranker", "重排序模型名称"),
    "USE_RERANKER": ("Reranker", "是否启用重排序"),
    "VECTOR_STORE_TYPE": ("向量数据库", "向量存储类型（lancedb/qdrant）"),
    "VECTOR_DB_URI": ("向量数据库", "向量数据库 URI"),
    "VECTOR_TABLE_NAME": ("向量数据库", "向量表名称"),
    "QDRANT_URL": ("向量数据库", "Qdrant 服务器地址"),
    "QDRANT_API_KEY": ("向量数据库", "Qdrant API 密钥"),
    "CHUNK_SIZE": ("任务处理", "文本分块大小"),
    "CHUNK_OVERLAP": ("任务处理", "文本分块重叠"),
    "EMBED_BATCH_SIZE": ("任务处理", "Embedding 批处理大小"),
    "PROGRESS_UPDATE_INTERVAL": ("任务处理", "进度更新间隔"),
    "MAX_CONCURRENT_TASKS": ("任务处理", "最大并发任务数"),
}


def handle_config_list(_: argparse.Namespace) -> int:
    settings = get_settings()
    categories: dict[str, list[dict[str, str]]] = {}
    for key, (category, description) in CONFIG_OPTION_DESCRIPTIONS.items():
        if category not in categories:
            categories[category] = []
        current_value = getattr(settings, key.lower(), None)
        if current_value is None:
            current_value = os.getenv(key, "")
        categories[category].append(
            {
                "key": key,
                "value": str(current_value) if current_value else "",
                "description": description,
            }
        )

    for category, items in sorted(categories.items()):
        print(f"\n{'=' * 60}")
        print(f"📁 {category}")
        print(f"{'=' * 60}")
        print(f"  {'配置项':<30} {'值':<20} {'说明'}")
        print(f"  {'-' * 30} {'-' * 20} {'-' * 30}")
        for item in items:
            value = item["value"]
            if len(value) > 18:
                value = value[:15] + "..."
            print(f"  {item['key']:<30} {value:<20} {item['description']}")
    print()
    return 0


def handle_config_get(args: argparse.Namespace) -> int:
    settings = get_settings()
    key = args.key.upper()

    if key in CONFIG_OPTION_DESCRIPTIONS:
        category, description = CONFIG_OPTION_DESCRIPTIONS[key]
        value = getattr(settings, key.lower(), None) or os.getenv(key, "")
        print(f"配置项: {key}")
        print(f"类别: {category}")
        print(f"说明: {description}")
        print(f"当前值: {value if value else '(未设置)'}")
    else:
        value = os.getenv(key, "")
        if value:
            print(f"配置项: {key}")
            print(f"当前值: {value}")
        else:
            print(f"错误: 未知配置项 '{key}'")
            return 1
    return 0


def handle_config_set(args: argparse.Namespace) -> int:
    key = args.key.upper()
    value = args.value

    if key not in CONFIG_OPTION_DESCRIPTIONS:
        print(f"警告: '{key}' 不是已知配置项，但仍会写入 .env")

    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print(f"错误: .env 文件不存在: {env_path}")
        return 1

    lines = []
    found = False
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = []
    key_pattern = f"{key}="
    for line in lines:
        if line.startswith(key_pattern):
            stripped = line.lstrip()
            if stripped.startswith(key_pattern):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"✅ 已设置 {key}={value}")
    print(f"   (已写入 .env 文件)")
    print(f"\n⚠️  部分配置需要重启服务才能生效")
    return 0


def _env_to_attr(env_key: str) -> str:
    """将环境变量名转换为 Settings 属性名"""
    # 简单转换：直接尝试 lower() 开头的属性
    attr = env_key.lower()
    return attr


def handle_config_get(args: argparse.Namespace) -> int:
    """获取指定配置项的值"""
    settings = get_settings()
    key = args.key.upper()

    # 检查是否是已知配置项
    if key in CONFIG_OPTION_DESCRIPTIONS:
        category, description = CONFIG_OPTION_DESCRIPTIONS[key]
        attr = _env_to_attr(key)
        value = getattr(settings, attr, None) or os.getenv(key, "")
        print(f"配置项: {key}")
        print(f"类别: {category}")
        print(f"说明: {description}")
        print(f"当前值: {value if value else '(未设置)'}")
    else:
        # 尝试直接获取
        value = os.getenv(key, "")
        if value:
            print(f"配置项: {key}")
            print(f"当前值: {value}")
        else:
            print(f"错误: 未知配置项 '{key}'")
            return 1
    return 0


def handle_config_set(args: argparse.Namespace) -> int:
    """设置配置项的值（写入 .env 文件）"""
    key = args.key.upper()
    value = args.value

    # 检查是否是已知配置项
    if key not in CONFIG_OPTION_DESCRIPTIONS:
        print(f"警告: '{key}' 不是已知配置项，但仍会写入 .env")

    # 确定 .env 文件路径
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print(f"错误: .env 文件不存在: {env_path}")
        return 1

    # 读取现有内容
    lines = []
    found = False
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            lines = f.readlines()

    # 查找并更新或追加
    new_lines = []
    key_pattern = f"{key}="
    for line in lines:
        if line.startswith(key_pattern):
            # 处理注释行（如 # KEY=...）
            stripped = line.lstrip()
            if stripped.startswith(key_pattern):
                new_lines.append(f"{key}={value}\n")
                found = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    if not found:
        # 追加新配置
        new_lines.append(f"{key}={value}\n")

    # 写回文件
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"✅ 已设置 {key}={value}")
    print(f"   (已写入 .env 文件)")
    print(f"\n⚠️  部分配置需要重启服务才能生效")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llamaindex-study", description="LlamaIndex Study 统一 CLI"
    )
    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser("chat", help="启动交互式问答")
    chat_parser.set_defaults(handler=lambda _: run_interactive())

    kb_parser = subparsers.add_parser("kb", help="知识库管理")
    kb_sub = kb_parser.add_subparsers(dest="kb_command", required=True)

    kb_list = kb_sub.add_parser("list", help="列出知识库")
    kb_list.set_defaults(handler=handle_kb_list)

    kb_show = kb_sub.add_parser("show", help="查看知识库详情")
    kb_show.add_argument("kb_id")
    kb_show.set_defaults(handler=handle_kb_show)

    kb_create = kb_sub.add_parser("create", help="创建知识库")
    kb_create.add_argument("kb_id")
    kb_create.add_argument("--name", required=True)
    kb_create.add_argument("--description", default="")
    kb_create.set_defaults(handler=handle_kb_create)

    kb_delete = kb_sub.add_parser("delete", help="删除知识库")
    kb_delete.add_argument("kb_id")
    kb_delete.add_argument("--yes", action="store_true")
    kb_delete.set_defaults(handler=handle_kb_delete)

    kb_initialize = kb_sub.add_parser("initialize", help="初始化知识库（清空所有数据）")
    kb_initialize.add_argument("kb_id")
    kb_initialize.set_defaults(handler=handle_kb_initialize)

    kb_topics = kb_sub.add_parser("topics", help="分析知识库主题词（使用远程LLM）")
    kb_topics.add_argument("kb_id", nargs="?", default=None)
    kb_topics.add_argument("--all", action="store_true", help="分析所有知识库")
    kb_topics.add_argument("--update", action="store_true", help="更新到数据库")
    kb_topics.set_defaults(handler=handle_kb_topics)

    kb_topics_local = kb_sub.add_parser(
        "topics-local", help="分析知识库主题词（使用本地模型）"
    )
    kb_topics_local.add_argument("kb_id", nargs="?", default=None)
    kb_topics_local.add_argument("--all", action="store_true", help="分析所有知识库")
    kb_topics_local.add_argument("--update", action="store_true", help="更新到数据库")
    kb_topics_local.set_defaults(handler=handle_kb_topics_local)

    search_parser = subparsers.add_parser("search", help="检索知识库")
    search_parser.add_argument(
        "kb_id", nargs="?", default=None, help="知识库 ID（省略时自动选择）"
    )
    search_parser.add_argument("query", nargs="*", default=None, help="查询内容")
    search_parser.add_argument("-k", "--top-k", type=int, default=5)
    search_parser.add_argument("--auto", action="store_true", help="自动选择知识库")
    search_parser.add_argument(
        "--exclude", help="排除的知识库 ID（逗号分隔，如: tech_tools,academic）"
    )
    search_parser.add_argument(
        "--kb-ids", help="指定多个知识库 ID（逗号分隔，如: kb1,kb2,kb3）"
    )
    search_parser.add_argument(
        "--auto-merging",
        action="store_true",
        help="启用 Auto-Merging（合并子节点到父节点）",
    )
    search_parser.set_defaults(handler=handle_search)

    query_parser = subparsers.add_parser("query", help="知识库问答")
    query_parser.add_argument(
        "kb_id", nargs="?", default=None, help="知识库 ID（省略时自动选择）"
    )
    query_parser.add_argument("query", nargs="*", default=None, help="查询内容")
    query_parser.add_argument("-k", "--top-k", type=int, default=5)
    query_parser.add_argument("--auto", action="store_true", help="自动选择知识库")
    query_parser.add_argument(
        "--exclude", help="排除的知识库 ID（逗号分隔，如: tech_tools,academic）"
    )
    query_parser.add_argument(
        "--kb-ids", help="指定多个知识库 ID（逗号分隔，如: kb1,kb2,kb3）"
    )
    query_parser.add_argument("--hyde", action="store_true", help="启用 HyDE 查询转换")
    query_parser.add_argument(
        "--multi-query", action="store_true", help="启用多查询转换"
    )
    query_parser.add_argument(
        "--auto-merging", action="store_true", help="启用 Auto-Merging Retriever"
    )
    query_parser.add_argument(
        "--response-mode",
        choices=[
            "compact",
            "refine",
            "tree_summarize",
            "simple",
            "no_text",
            "accumulate",
        ],
        default=None,
        help="答案生成模式（默认使用配置值）",
    )
    query_parser.set_defaults(handler=handle_query)

    ingest_parser = subparsers.add_parser("ingest", help="提交导入任务")
    ingest_sub = ingest_parser.add_subparsers(dest="ingest_command", required=True)

    ingest_obsidian = ingest_sub.add_parser("obsidian", help="导入 Obsidian 目录")
    ingest_obsidian.add_argument("kb_id")
    ingest_obsidian.add_argument(
        "--vault-path", default=str(Path.home() / "Documents" / "Obsidian Vault")
    )
    ingest_obsidian.add_argument("--folder-path")
    ingest_obsidian.add_argument(
        "--recursive", action=argparse.BooleanOptionalAction, default=True
    )
    ingest_obsidian.add_argument("--rebuild", action="store_true")
    ingest_obsidian.add_argument(
        "--force-delete", action=argparse.BooleanOptionalAction, default=True
    )
    ingest_obsidian.add_argument("--persist-dir")
    ingest_obsidian.set_defaults(handler=handle_ingest_obsidian)

    ingest_zotero = ingest_sub.add_parser("zotero", help="导入 Zotero 收藏夹")
    ingest_zotero.add_argument("kb_id")
    ingest_zotero.add_argument("--collection-id")
    ingest_zotero.add_argument("--collection-name")
    ingest_zotero.add_argument("--rebuild", action="store_true")
    ingest_zotero.set_defaults(handler=handle_ingest_zotero)

    ingest_file = ingest_sub.add_parser("file", help="导入单个文件或目录")
    ingest_file.add_argument("kb_id")
    ingest_file.add_argument("path")
    ingest_file.set_defaults(handler=handle_ingest_file)

    ingest_batch = ingest_sub.add_parser("batch", help="批量导入多个路径")
    ingest_batch.add_argument("kb_id")
    ingest_batch.add_argument("paths", nargs="+")
    ingest_batch.add_argument(
        "--include",
        help="只处理指定的文件格式 (如: pdf,md,docx)，逗号分隔。不指定则使用默认格式",
    )
    ingest_batch.add_argument(
        "--exclude",
        help="从默认格式中排除指定的文件格式 (如: xlsx,png)，逗号分隔",
    )
    ingest_batch.set_defaults(handler=handle_ingest_batch)

    ingest_rebuild = ingest_sub.add_parser(
        "rebuild", help="重建知识库（清空后重新导入）"
    )
    ingest_rebuild.add_argument("kb_id")
    ingest_rebuild.set_defaults(handler=handle_ingest_rebuild)

    obsidian_parser = subparsers.add_parser("obsidian", help="Obsidian 辅助命令")
    obsidian_sub = obsidian_parser.add_subparsers(
        dest="obsidian_command", required=True
    )

    obsidian_vaults = obsidian_sub.add_parser("vaults", help="列出可用 Vault")
    obsidian_vaults.set_defaults(handler=handle_obsidian_vaults)

    obsidian_info = obsidian_sub.add_parser("info", help="查看 Vault 信息")
    obsidian_info.add_argument("vault_name")
    obsidian_info.set_defaults(handler=handle_obsidian_info)

    obsidian_mappings = obsidian_sub.add_parser("mappings", help="列出目录映射")
    obsidian_mappings.set_defaults(handler=handle_obsidian_mappings)

    obsidian_import_all = obsidian_sub.add_parser(
        "import-all", help="批量提交所有 Obsidian 导入任务"
    )
    obsidian_import_all.add_argument(
        "--vault-path", default=str(Path.home() / "Documents" / "Obsidian Vault")
    )
    obsidian_import_all.add_argument("--rebuild", action="store_true")
    obsidian_import_all.add_argument(
        "--force-delete", action=argparse.BooleanOptionalAction, default=True
    )
    obsidian_import_all.set_defaults(handler=handle_obsidian_import_all)

    zotero_parser = subparsers.add_parser("zotero", help="Zotero 辅助命令")
    zotero_sub = zotero_parser.add_subparsers(dest="zotero_command", required=True)

    zotero_collections = zotero_sub.add_parser("collections", help="列出收藏夹")
    zotero_collections.add_argument("--limit", type=int, default=50)
    zotero_collections.set_defaults(handler=handle_zotero_collections)

    zotero_search = zotero_sub.add_parser("search", help="搜索收藏夹")
    zotero_search.add_argument("keyword")
    zotero_search.set_defaults(handler=handle_zotero_search)

    task_parser = subparsers.add_parser(
        "task",
        help="任务管理：查看、暂停、恢复、取消、删除任务等",
    )
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)

    task_submit = task_sub.add_parser(
        "submit",
        help="提交自定义任务（通常不需要手动使用，导入命令会自动提交任务）",
        description="提交自定义任务到任务队列",
    )
    task_submit.add_argument(
        "task_type",
        help="任务类型，如: obsidian, generic, zotero, rebuild",
    )
    task_submit.add_argument("kb_id", help="知识库ID")
    task_submit.add_argument(
        "--param",
        action="append",
        help="任务参数，格式: key=value，可多次使用",
    )
    task_submit.add_argument(
        "--source",
        default="",
        help="任务来源标识",
    )
    task_submit.set_defaults(handler=handle_task_submit)

    task_list = task_sub.add_parser(
        "list",
        help="列出任务",
        description="列出任务，支持按知识库ID、状态过滤。注意：此命令会自动清理孤儿任务（状态为running但实际无后台进程的任务）。",
    )
    task_list.add_argument(
        "--kb-id",
        help="按知识库ID过滤，如: tech_tools, research",
    )
    task_list.add_argument(
        "--status",
        help="按状态过滤，可选值: pending(等待中), running(运行中), paused(已暂停), completed(已完成), failed(失败), cancelled(已取消)",
    )
    task_list.add_argument(
        "--limit",
        type=int,
        default=20,
        help="返回任务数量上限，默认20",
    )
    task_list.set_defaults(handler=handle_task_list)

    task_show = task_sub.add_parser(
        "show",
        help="查看任务详情",
        description="查看单个任务的详细信息，包括进度、消息、结果等",
    )
    task_show.add_argument(
        "task_id",
        help="任务ID，从 task list 获取",
    )
    task_show.set_defaults(handler=handle_task_show)

    task_cancel = task_sub.add_parser(
        "cancel",
        help="取消运行中的任务",
        description="取消正在运行的任务。任务会在当前文件处理完成后进入已取消状态。只能取消 pending 或 running 状态的任务。",
    )
    task_cancel.add_argument(
        "task_id",
        help="要取消的任务ID",
    )
    task_cancel.set_defaults(handler=handle_task_cancel)

    task_pause = task_sub.add_parser(
        "pause",
        help="暂停运行中的任务",
        description="暂停正在运行的任务。任务会在当前文件处理完成后进入暂停状态。可以使用 task resume 恢复执行。",
    )
    task_pause.add_argument(
        "task_id",
        help="要暂停的任务ID",
    )
    task_pause.set_defaults(handler=handle_task_pause)

    task_pause_all = task_sub.add_parser(
        "pause-all",
        help="暂停所有运行中的任务",
        description="批量暂停所有运行中的任务。默认暂停所有 running 状态的任务。",
    )
    task_pause_all.add_argument(
        "--status",
        default="running",
        help="要暂停的任务状态，默认 running",
    )
    task_pause_all.set_defaults(handler=handle_task_pause_all)

    task_resume = task_sub.add_parser(
        "resume",
        help="恢复已暂停的任务",
        description="恢复已暂停的任务，继续执行。只能恢复 paused 状态的任务。",
    )
    task_resume.add_argument(
        "task_id",
        help="要恢复的任务ID",
    )
    task_resume.set_defaults(handler=handle_task_resume)

    task_resume_all = task_sub.add_parser(
        "resume-all",
        help="恢复所有已暂停的任务",
        description="批量恢复所有已暂停的任务，继续执行。",
    )
    task_resume_all.set_defaults(handler=handle_task_resume_all)

    task_delete = task_sub.add_parser(
        "delete",
        help="删除任务记录",
        description="删除任务记录（物理删除）。只能删除 completed、failed、cancelled 状态的任务。running 状态的任务需要先取消。",
    )
    task_delete.add_argument(
        "task_id",
        help="要删除的任务ID",
    )
    task_delete.add_argument(
        "--cleanup",
        action="store_true",
        help="同时清理关联的知识库数据（去重记录 + 向量数据）。仅清理该任务产生的源文件数据，不影响其他数据。",
    )
    task_delete.set_defaults(handler=handle_task_delete)

    task_delete_all = task_sub.add_parser(
        "delete-all",
        help="删除所有任务",
        description="批量删除任务记录。默认删除所有 completed 状态的任务。",
    )
    task_delete_all.add_argument(
        "--status",
        default="completed",
        help="要删除的任务状态，默认 completed。可选: pending, running, paused, completed, failed, cancelled",
    )
    task_delete_all.add_argument(
        "--cleanup",
        action="store_true",
        help="同时清理关联的知识库数据（去重记录 + 向量数据）。",
    )
    task_delete_all.set_defaults(handler=handle_task_delete_all)

    task_cleanup = task_sub.add_parser(
        "cleanup",
        help="清理孤儿任务",
        description="清理孤儿任务。孤儿任务是指状态为 running 但实际没有后台进程执行的任务（通常是因为执行进程被终止）。",
    )
    task_cleanup.add_argument(
        "--no-cleanup",
        action="store_true",
        help="仅标记孤儿任务为 failed，不清理关联的向量数据（去重记录 + 向量数据）",
    )
    task_cleanup.set_defaults(handler=handle_task_cleanup)

    task_watch = task_sub.add_parser(
        "watch",
        help="持续观察任务状态",
        description="持续监控任务状态变化，有变化时打印最新状态。适用于观察长时间运行的任务。",
    )
    task_watch.add_argument(
        "task_id",
        help="要观察的任务ID",
    )
    task_watch.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="检查间隔时间（秒），默认1秒",
    )
    task_watch.add_argument(
        "--timeout",
        type=float,
        default=0,
        help="超时时间（秒），默认0表示不限时。超时后退出观察。",
    )
    task_watch.set_defaults(handler=handle_task_watch)

    category_parser = subparsers.add_parser("category", help="分类规则与分类辅助")
    category_sub = category_parser.add_subparsers(
        dest="category_command", required=True
    )

    category_rules = category_sub.add_parser("rules", help="分类规则管理")
    category_rules_sub = category_rules.add_subparsers(
        dest="rules_command", required=True
    )

    rules_list = category_rules_sub.add_parser("list", help="列出分类规则")
    rules_list.set_defaults(handler=handle_category_rules_list)

    rules_sync = category_rules_sub.add_parser("sync", help="同步映射规则到数据库")
    rules_sync.set_defaults(handler=handle_category_rules_sync)

    rules_add = category_rules_sub.add_parser("add", help="新增分类规则")
    rules_add.add_argument("--kb-id", required=True)
    rules_add.add_argument("--rule-type", required=True)
    rules_add.add_argument("--pattern", required=True)
    rules_add.add_argument("--description", default="")
    rules_add.add_argument("--priority", type=int, default=0)
    rules_add.set_defaults(handler=handle_category_rules_add)

    rules_delete = category_rules_sub.add_parser("delete", help="删除分类规则")
    rules_delete.add_argument("--kb-id", required=True)
    rules_delete.add_argument("--rule-type", required=True)
    rules_delete.add_argument("--pattern", required=True)
    rules_delete.set_defaults(handler=handle_category_rules_delete)

    category_classify = category_sub.add_parser("classify", help="对文件夹执行分类")
    category_classify.add_argument("folder_path")
    category_classify.add_argument("--description", default="")
    category_classify.add_argument(
        "--use-llm", action=argparse.BooleanOptionalAction, default=True
    )
    category_classify.set_defaults(handler=handle_category_classify)

    admin_parser = subparsers.add_parser("admin", help="管理命令")
    admin_sub = admin_parser.add_subparsers(dest="admin_command", required=True)

    admin_tables = admin_sub.add_parser("tables", help="列出向量表")
    admin_tables.set_defaults(handler=handle_admin_tables)

    admin_table = admin_sub.add_parser("table", help="查看向量表详情")
    admin_table.add_argument("kb_id")
    admin_table.set_defaults(handler=handle_admin_table)

    admin_delete = admin_sub.add_parser("delete-table", help="删除向量表")
    admin_delete.add_argument("kb_id")
    admin_delete.add_argument("--yes", action="store_true")
    admin_delete.set_defaults(handler=handle_admin_delete)

    config_parser = subparsers.add_parser("config", help="配置管理")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)

    config_list = config_sub.add_parser("list", help="列出所有配置选项")
    config_list.set_defaults(handler=handle_config_list)

    config_get = config_sub.add_parser("get", help="获取指定配置项的值")
    config_get.add_argument("key", help="配置项名称（如 OLLAMA_EMBED_MODEL）")
    config_get.set_defaults(handler=handle_config_get)

    config_set = config_sub.add_parser("set", help="设置配置项的值")
    config_set.add_argument("key", help="配置项名称（如 OLLAMA_EMBED_MODEL）")
    config_set.add_argument("value", help="配置值")
    config_set.set_defaults(handler=handle_config_set)

    return parser


def main() -> int:
    if len(sys.argv) == 1:
        return run_interactive()

    parser = build_parser()
    args = parser.parse_args()
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
