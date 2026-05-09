"""
知识库数据变化监控脚本

通过快照对比，追踪指定 KB 在时间窗口内的数据变化。

用法:
  uv run python scripts/monitor_kb.py <kb_id>             # 单次快照
  uv run python scripts/monitor_kb.py <kb_id> --watch 10  # 每 10 秒对比一次
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _snapshot(kb_id: str) -> dict:
    import sqlite3
    from pathlib import Path

    project_db = Path.home() / ".llamaindex" / "project.db"
    tasks_db = Path.home() / ".llamaindex" / "tasks.db"
    stats_db = Path.home() / ".llamaindex" / "stats" / "token_stats.db"

    snap = {"kb_id": kb_id, "time": time.time()}

    try:
        conn = sqlite3.connect(str(project_db))
        rows = conn.execute(
            "SELECT embedding_generated, COUNT(*) FROM chunks WHERE kb_id=? GROUP BY embedding_generated",
            (kb_id,),
        ).fetchall()
        conn.close()
        snap["chunks"] = {r[0]: r[1] for r in rows}
    except Exception:
        snap["chunks"] = {}

    # SQLite documents
    try:
        conn = sqlite3.connect(str(project_db))
        count = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE kb_id=?", (kb_id,)
        ).fetchone()[0]
        conn.close()
        snap["documents"] = count
    except Exception:
        snap["documents"] = 0

    try:
        conn = sqlite3.connect(str(tasks_db))
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM tasks WHERE kb_id=? GROUP BY status",
            (kb_id,),
        ).fetchall()
        conn.close()
        snap["tasks"] = {r[0]: r[1] for r in rows}
        running = conn.execute(
            "SELECT task_id, task_type, progress, message FROM tasks WHERE kb_id=? AND status='running'",
            (kb_id,),
        ).fetchall()
        if running:
            snap["tasks_running"] = [
                {"id": r[0], "type": r[1], "progress": r[2], "msg": r[3]}
                for r in running
            ]
    except Exception:
        snap["tasks"] = {}

    # Model calls (observability)
    try:
        if Path(stats_db).exists():
            conn = sqlite3.connect(str(stats_db))
            rows = conn.execute(
                "SELECT model_name, COUNT(*) as cnt FROM rag_trace_events GROUP BY model_name"
            ).fetchall()
            conn.close()
            snap["model_calls"] = {r[0]: r[1] for r in rows}
        else:
            snap["model_calls"] = {}
    except Exception:
        snap["model_calls"] = {}

    return snap


def _diff(prev: dict, curr: dict) -> list:
    lines = []
    elapsed = curr["time"] - prev["time"]

    # Chunks
    prev_chunks = prev.get("chunks", {})
    curr_chunks = curr.get("chunks", {})
    all_statuses = set(list(prev_chunks.keys()) + list(curr_chunks.keys()))
    for s in sorted(all_statuses):
        p = prev_chunks.get(s, 0)
        c = curr_chunks.get(s, 0)
        if p != c:
            label = {0: "pending", 1: "success", 2: "failed"}.get(s, str(s))
            delta = c - p
            lines.append(f"  chunks [{label}]: {p} → {c} ({delta:+d})")

    # Documents
    if prev.get("documents", 0) != curr.get("documents", 0):
        lines.append(
            f"  documents: {prev['documents']} → {curr['documents']} ({curr['documents'] - prev['documents']:+d})"
        )

    # Tasks
    prev_tasks = prev.get("tasks", {})
    curr_tasks = curr.get("tasks", {})
    all_statuses = set(list(prev_tasks.keys()) + list(curr_tasks.keys()))
    for s in sorted(all_statuses):
        p = prev_tasks.get(s, 0)
        c = curr_tasks.get(s, 0)
        if p != c:
            lines.append(f"  tasks [{s}]: {p} → {c} ({c - p:+d})")

    # Model calls
    prev_models = prev.get("model_calls", {})
    curr_models = curr.get("model_calls", {})
    all_models = set(list(prev_models.keys()) + list(curr_models.keys()))
    for m in sorted(all_models):
        p = prev_models.get(m, 0)
        c = curr_models.get(m, 0)
        if p != c:
            lines.append(f"  model [{m[:60]}]: {p} → {c} ({c - p:+d} calls)")

    # Running tasks (always show)
    if curr.get("tasks_running"):
        for t in curr["tasks_running"]:
            lines.append(
                f"  ⚠️  RUNNING: {t['id'][:8]} {t['type']} {t['progress']}% {t['msg'][:60]}"
            )

    if not lines:
        lines.append("  (无变化)")

    return lines, elapsed


def main():
    parser = argparse.ArgumentParser(description="KB 数据变化监控")
    parser.add_argument("kb_id", help="知识库 ID")
    parser.add_argument("--watch", type=int, metavar="SEC", help="持续监控间隔(秒)")
    args = parser.parse_args()

    prev = _snapshot(args.kb_id)

    print(f"[{args.kb_id}] 基线快照 ({time.strftime('%H:%M:%S')}):")
    print(f"  documents: {prev['documents']}")
    chunks = prev.get("chunks", {})
    for s in sorted(chunks.keys()):
        label = {0: "pending", 1: "success", 2: "failed"}.get(s, str(s))
        print(f"  chunks [{label}]: {chunks[s]}")
    tasks = prev.get("tasks", {})
    for s in sorted(tasks.keys()):
        print(f"  tasks [{s}]: {tasks[s]}")
    models = prev.get("model_calls", {})
    for m in sorted(models.keys()):
        print(f"  model [{m[:60]}]: {models[m]} calls")

    if not args.watch:
        return

    print(f"\n每 {args.watch}s 检测一次，Ctrl+C 退出...")

    try:
        while True:
            time.sleep(args.watch)
            curr = _snapshot(args.kb_id)
            diffs, elapsed = _diff(prev, curr)
            if any("(无变化)" not in d for d in diffs):
                print(f"\n[{time.strftime('%H:%M:%S')}] 变化 (间隔 {elapsed:.0f}s):")
                for d in diffs:
                    print(d)
            prev = curr
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
