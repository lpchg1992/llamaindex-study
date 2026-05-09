#!/usr/bin/env python3
import json
import os
import sys
import urllib.request
import urllib.parse
from collections import defaultdict
from pathlib import Path

API_BASE = os.environ.get("API_BASE", "http://localhost:37241")
KB_ID = sys.argv[1] if len(sys.argv) > 1 else "animal-nutrition-breeding"
TAIL_CHARS = 400


def api_get(path: str) -> dict:
    url = f"{API_BASE}{path}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_documents(kb_id: str) -> list:
    return api_get(f"/kbs/{kb_id}/documents")


def get_last_chunk(kb_id: str, doc: dict) -> dict | None:
    doc_id = doc["id"]
    encoded = urllib.parse.quote(doc_id, safe="")
    data = api_get(f"/kbs/{kb_id}/documents/{encoded}/chunks?page=1&page_size=1")
    total = data.get("total", 0)
    if total == 0:
        return None
    data = api_get(
        f"/kbs/{kb_id}/documents/{encoded}/chunks?page={total}&page_size=1"
    )
    chunks = data.get("chunks", [])
    return chunks[0] if chunks else None


def read_source_tail(source_path: str, tail_chars: int) -> str | None:
    if not source_path or not os.path.exists(source_path):
        return None

    ext = Path(source_path).suffix.lower()

    if ext in (".md", ".txt", ".csv", ".json", ".xml", ".html"):
        try:
            with open(source_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return content[-tail_chars:]
        except Exception:
            return None

    if ext == ".docx":
        try:
            from docx import Document

            doc = Document(source_path)
            text = "\n".join(p.text for p in doc.paragraphs)
            return text[-tail_chars:] if text else None
        except Exception:
            return None

    if ext == ".pdf":
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(source_path)
            total_pages = len(reader.pages)
            pages_to_read = min(3, total_pages)
            text = ""
            for i in range(total_pages - pages_to_read, total_pages):
                text += (reader.pages[i].extract_text() or "") + "\n"
            return text[-tail_chars:] if text.strip() else None
        except Exception:
            return None

    return None


def text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a = a.strip().lower()
    b = b.strip().lower()
    if a == b:
        return 1.0

    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    n = min(20, len(shorter))
    matches = 0
    for i in range(0, len(longer) - n + 1, n):
        if longer[i : i + n] in shorter:
            matches += 1
    possible = max(1, len(longer) // n)
    return matches / possible


def looks_corrupted(text: str) -> bool:
    if not text:
        return False
    null_count = text.count("\x00")
    if null_count > len(text) * 0.3:
        return True
    return False


def ends_abruptly(text: str) -> bool:
    if not text or not text.strip():
        return True
    tail = text.strip()[-20:]
    if tail.isdigit():
        return False
    if any(tail.endswith(c) for c in (",", ";", "-", "(", "（", "、", "/")):
        return True
    return False


def main():
    print(f"知识库: {KB_ID}")
    print(f"API: {API_BASE}")
    print()

    docs = get_documents(KB_ID)
    print(f"文档总数: {len(docs)}")
    print()

    stats = defaultdict(int)
    stats["total"] = len(docs)
    suspicious_docs = []

    for i, doc in enumerate(docs):
        doc_id = doc["id"]
        source_path = doc.get("source_path", "")
        source_file = doc.get("source_file", doc_id[:40])

        try:
            last_chunk = get_last_chunk(KB_ID, doc)
        except Exception as e:
            print(f"  [{i+1}/{len(docs)}] ⚠️  {source_file[:50]} — API 错误: {e}")
            stats["errors"] += 1
            continue

        if not last_chunk:
            stats["skipped"] += 1
            continue

        stats["checked"] += 1
        chunk_text = last_chunk.get("text", "")
        chunk_len = len(chunk_text)
        emb_status = "✓" if last_chunk.get("embedding_generated") == 1 else "✗"

        source_tail = read_source_tail(source_path, TAIL_CHARS)
        sim = None

        if source_tail:
            sim = text_similarity(chunk_text[-TAIL_CHARS:], source_tail)
            if sim > 0.3:
                stats["matched"] += 1
                status = "✓"
            else:
                stats["suspicious"] += 1
                status = "⚠️"
                suspicious_docs.append({
                    "source_file": source_file,
                    "source_path": source_path,
                    "chunk_len": chunk_len,
                    "similarity": sim,
                    "chunk_tail": chunk_text[-200:],
                    "source_tail": source_tail[-200:],
                })
        elif looks_corrupted(chunk_text):
            stats["suspicious"] += 1
            status = "⚠️"
            suspicious_docs.append({
                "source_file": source_file,
                "source_path": source_path,
                "chunk_len": chunk_len,
                "chunk_tail": chunk_text[-200:],
                "reason": "chunk 内容异常（大量空字节）",
            })
        elif ends_abruptly(chunk_text):
            stats["suspicious"] += 1
            status = "?"
            suspicious_docs.append({
                "source_file": source_file,
                "source_path": source_path,
                "chunk_len": chunk_len,
                "chunk_tail": chunk_text[-200:],
                "reason": "chunk 以逗号/分号等非自然方式结尾",
            })
        else:
            stats["natural_end"] += 1
            status = "~"

        src_info = f"src_sim={sim:.2f}" if source_tail else "源文件不可读"
        print(
            f"  [{i+1:3d}/{len(docs)}] {status} {emb_status} "
            f"{source_file[:45]:45s} chunk_len={chunk_len:5d}  {src_info}"
        )

        if (i + 1) % 20 == 0:
            sys.stdout.flush()

    print()
    print("=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"  总文档数:       {stats['total']}")
    print(f"  已检查:         {stats['checked']}")
    print(f"  与源文件匹配:   {stats['matched']}  ✓")
    print(f"  自然结尾:       {stats['natural_end']}  ~")
    print(f"  可疑截断:       {stats['suspicious']}  ⚠️")
    print(f"  跳过(无chunk):  {stats['skipped']}")
    print(f"  错误:           {stats['errors']}")

    if suspicious_docs:
        print()
        print("=" * 60)
        print("可疑文档详情")
        print("=" * 60)
        for sd in suspicious_docs:
            print(f"\n  文档: {sd['source_file'][:60]}")
            if "similarity" in sd:
                print(f"  相似度: {sd['similarity']:.2f}")
                print(f"  chunk 尾部 (200 chars):")
                print(f"  ---\n  {sd['chunk_tail'][:200]}\n  ---")
                print(f"  源文件尾部 (200 chars):")
                print(f"  ---\n  {sd['source_tail'][:200]}\n  ---")
            else:
                print(f"  原因: {sd.get('reason', 'unknown')}")
                print(f"  chunk 尾部 (200 chars):")
                print(f"  ---\n  {sd['chunk_tail'][:200]}\n  ---")

    return 0 if stats["suspicious"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
