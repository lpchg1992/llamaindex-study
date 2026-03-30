#!/usr/bin/env python3
import argparse
import json
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
    task_type: str, kb_id: str, params: dict[str, Any], source: str, wait: bool
) -> int:
    result = TaskService.submit(
        task_type=task_type, kb_id=kb_id, params=params, source=source
    )
    if wait:
        task = TaskService.run_task(result["task_id"])
        print_json(task)
    else:
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


def handle_kb_rebuild(args: argparse.Namespace) -> int:
    return submit_task_and_handle(
        "rebuild", args.kb_id, {}, source="cli:kb:rebuild", wait=args.wait
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

    if getattr(args, "auto", False):
        from kb.services import QueryRouter

        exclude = getattr(args, "exclude", None)
        if exclude:
            exclude = [e.strip() for e in exclude.split(",") if e.strip()]
        result = QueryRouter.search(query, top_k=args.top_k, exclude=exclude)
    else:
        result = SearchService.search(args.kb_id, query, top_k=args.top_k)
    print_json(result)
    return 0


def handle_query(args: argparse.Namespace) -> int:
    query = get_query_from_args_or_stdin(args)
    if not query:
        print("错误: 请提供查询内容", file=sys.stderr)
        return 1

    if getattr(args, "auto", False):
        from kb.services import QueryRouter

        exclude = getattr(args, "exclude", None)
        if exclude:
            exclude = [e.strip() for e in exclude.split(",") if e.strip()]
        result = QueryRouter.query(query, top_k=args.top_k, exclude=exclude)
    else:
        result = SearchService.query(args.kb_id, query, top_k=args.top_k)
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
        wait=args.wait,
    )


def handle_ingest_zotero(args: argparse.Namespace) -> int:
    params = {
        "collection_id": args.collection_id,
        "collection_name": args.collection_name,
        "rebuild": args.rebuild,
    }
    source = args.collection_name or args.collection_id or "zotero"
    return submit_task_and_handle(
        "zotero", args.kb_id, params, source=source, wait=args.wait
    )


def handle_ingest_file(args: argparse.Namespace) -> int:
    return submit_task_and_handle(
        "generic", args.kb_id, {"paths": [args.path]}, source=args.path, wait=args.wait
    )


def handle_ingest_batch(args: argparse.Namespace) -> int:
    return submit_task_and_handle(
        "generic",
        args.kb_id,
        {"paths": args.paths},
        source=args.paths[0],
        wait=args.wait,
    )


def handle_ingest_rebuild(args: argparse.Namespace) -> int:
    return submit_task_and_handle(
        "rebuild", args.kb_id, {}, source="cli:ingest:rebuild", wait=args.wait
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
            if args.wait:
                submission = TaskService.run_task(submission["task_id"])
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
        args.task_type, args.kb_id, params, source=args.source or "", wait=args.wait
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


def handle_task_delete(args: argparse.Namespace) -> int:
    print_json(TaskService.delete(args.task_id, cleanup=args.cleanup))
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

    kb_rebuild = kb_sub.add_parser("rebuild", help="重建知识库")
    kb_rebuild.add_argument("kb_id")
    kb_rebuild.add_argument("--wait", action="store_true")
    kb_rebuild.set_defaults(handler=handle_kb_rebuild)

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
    ingest_obsidian.add_argument("--wait", action="store_true")
    ingest_obsidian.set_defaults(handler=handle_ingest_obsidian)

    ingest_zotero = ingest_sub.add_parser("zotero", help="导入 Zotero 收藏夹")
    ingest_zotero.add_argument("kb_id")
    ingest_zotero.add_argument("--collection-id")
    ingest_zotero.add_argument("--collection-name")
    ingest_zotero.add_argument("--rebuild", action="store_true")
    ingest_zotero.add_argument("--wait", action="store_true")
    ingest_zotero.set_defaults(handler=handle_ingest_zotero)

    ingest_file = ingest_sub.add_parser("file", help="导入单个文件或目录")
    ingest_file.add_argument("kb_id")
    ingest_file.add_argument("path")
    ingest_file.add_argument("--wait", action="store_true")
    ingest_file.set_defaults(handler=handle_ingest_file)

    ingest_batch = ingest_sub.add_parser("batch", help="批量导入多个路径")
    ingest_batch.add_argument("kb_id")
    ingest_batch.add_argument("paths", nargs="+")
    ingest_batch.add_argument("--wait", action="store_true")
    ingest_batch.set_defaults(handler=handle_ingest_batch)

    ingest_rebuild = ingest_sub.add_parser("rebuild", help="提交重建任务")
    ingest_rebuild.add_argument("kb_id")
    ingest_rebuild.add_argument("--wait", action="store_true")
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
    obsidian_import_all.add_argument("--wait", action="store_true")
    obsidian_import_all.set_defaults(handler=handle_obsidian_import_all)

    zotero_parser = subparsers.add_parser("zotero", help="Zotero 辅助命令")
    zotero_sub = zotero_parser.add_subparsers(dest="zotero_command", required=True)

    zotero_collections = zotero_sub.add_parser("collections", help="列出收藏夹")
    zotero_collections.add_argument("--limit", type=int, default=50)
    zotero_collections.set_defaults(handler=handle_zotero_collections)

    zotero_search = zotero_sub.add_parser("search", help="搜索收藏夹")
    zotero_search.add_argument("keyword")
    zotero_search.set_defaults(handler=handle_zotero_search)

    task_parser = subparsers.add_parser("task", help="任务管理")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)

    task_submit = task_sub.add_parser("submit", help="提交自定义任务")
    task_submit.add_argument("task_type")
    task_submit.add_argument("kb_id")
    task_submit.add_argument("--param", action="append")
    task_submit.add_argument("--source", default="")
    task_submit.add_argument("--wait", action="store_true")
    task_submit.set_defaults(handler=handle_task_submit)

    task_list = task_sub.add_parser("list", help="列出任务")
    task_list.add_argument("--kb-id")
    task_list.add_argument("--status")
    task_list.add_argument("--limit", type=int, default=20)
    task_list.set_defaults(handler=handle_task_list)

    task_show = task_sub.add_parser("show", help="查看任务详情")
    task_show.add_argument("task_id")
    task_show.set_defaults(handler=handle_task_show)

    task_cancel = task_sub.add_parser("cancel", help="取消任务")
    task_cancel.add_argument("task_id")
    task_cancel.set_defaults(handler=handle_task_cancel)

    task_delete = task_sub.add_parser("delete", help="删除任务")
    task_delete.add_argument("task_id")
    task_delete.add_argument(
        "--cleanup",
        action="store_true",
        help="同时清理关联的知识库数据（仅对 failed/cancelled 任务有效）",
    )
    task_delete.set_defaults(handler=handle_task_delete)

    task_watch = task_sub.add_parser("watch", help="持续观察任务状态")
    task_watch.add_argument("task_id")
    task_watch.add_argument("--interval", type=float, default=1.0)
    task_watch.add_argument("--timeout", type=float, default=0)
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
