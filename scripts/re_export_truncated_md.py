#!/usr/bin/env python3
"""
**独立脚本**
Re-export truncated md files using their UIDs (no OCR credit consumed).

This script:
1. Scans mddocs directory for truncated md files
2. Extracts UID from each truncated file
3. Uses doc2x_convert_export_* to get full markdown (no re-OCR)
4. Overwrites the truncated file with complete content
5. Updates meta.json to mark as not truncated (triggers re-import)
"""

import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ConversionMetadata:
    uid: str = None
    mineru_batch_id: str = None
    is_truncated: bool = False
    converted_at: str = None
    source_pdf: str = None
    page_count: int = 0

    def save(self, md_path: Path) -> None:
        meta_path = md_path.with_suffix(".meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)


def asdict(obj):
    return {k: v for k, v in obj.__dataclass_fields__.items() if v.init}


def load_env():
    """Load .env file"""
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value


def extract_truncated_info(md_content: str) -> dict | None:
    pattern = r"Output truncated \(pages (\d+)/(\d+), uid=([a-f0-9\-]+)\)"
    match = re.search(pattern, md_content)
    if match:
        return {
            "pages_done": int(match.group(1)),
            "pages_total": int(match.group(2)),
            "uid": match.group(3),
        }
    return None


def export_full_markdown_from_uid(
    uid: str, api_key: str, timeout: int = 300
) -> str | None:
    """使用已有 UID 导出完整 markdown（不消耗 OCR 额度）"""
    proc = None
    try:
        proc = subprocess.Popen(
            ["node", "/tmp/doc2x_mcp/node_modules/.bin/doc2x-mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ,
        )

        init_msg = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "llamaindex-study", "version": "0.1"},
            },
        }

        proc.stdin.write(json.dumps(init_msg) + "\n")
        proc.stdin.flush()
        time.sleep(2)

        submit_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "doc2x_convert_export_submit",
                "arguments": {"uid": uid, "to": "md", "formula_mode": "normal"},
            },
        }
        proc.stdin.write(json.dumps(submit_msg) + "\n")
        proc.stdin.flush()
        time.sleep(2)

        wait_msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "doc2x_convert_export_wait",
                "arguments": {"uid": uid, "to": "md", "poll_interval": 3000},
            },
        }
        proc.stdin.write(json.dumps(wait_msg) + "\n")
        proc.stdin.flush()

        start_time = time.time()
        export_url = None
        while time.time() - start_time < timeout:
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.5)
                continue
            try:
                resp = json.loads(line.strip())
                if resp.get("id") == 2 and "result" in resp:
                    result = resp["result"]
                    if isinstance(result, dict):
                        content = result.get("content", [])
                        if content:
                            text = content[0].get("text", "")
                            if text:
                                try:
                                    data = json.loads(text)
                                    url = data.get("url")
                                    if url and data.get("status") == "success":
                                        export_url = url
                                        break
                                except json.JSONDecodeError:
                                    pass
            except json.JSONDecodeError:
                continue

        proc.terminate()

        if export_url:
            try:
                req = urllib.request.Request(export_url)
                with urllib.request.urlopen(req, timeout=120) as response:
                    zip_data = response.read()
                    with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                        images_dir = Path("/Volumes/online/llamaindex/mddocs/images")
                        for name in zf.namelist():
                            if name == "output.md":
                                return zf.read(name).decode("utf-8")
                            elif name.startswith("images/") and not name.endswith("/"):
                                img_data = zf.read(name)
                                img_name = Path(name).name
                                img_path = images_dir / img_name
                                img_path.parent.mkdir(parents=True, exist_ok=True)
                                img_path.write_bytes(img_data)
            except Exception as e:
                print(f"      Download error: {e}")

        return None

    except Exception:
        if proc:
            proc.kill()
    return None


def main():
    load_env()

    api_key = os.getenv("DOC2X_API_KEY")
    if not api_key:
        print("❌ DOC2X_API_KEY not set")
        sys.exit(1)

    mddocs_dir = Path("/Volumes/online/llamaindex/mddocs")
    if not mddocs_dir.exists():
        print(f"❌ Directory not found: {mddocs_dir}")
        sys.exit(1)

    md_files = list(mddocs_dir.glob("*.md"))
    truncated_files = []

    print(f"🔍 Scanning {len(md_files)} md files...")

    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8")
            info = extract_truncated_info(content)
            if info:
                truncated_files.append((md_file, info))
        except Exception as e:
            print(f"   ⚠️  Read failed {md_file.name}: {e}")

    print(f"📊 Found {len(truncated_files)} truncated files")

    if not truncated_files:
        print("✅ No files need re-export")
        sys.exit(0)

    success_count = 0
    fail_count = 0

    for md_file, info in truncated_files:
        uid = info["uid"]
        pages_total = info["pages_total"]
        print(f"\n🔄 Re-exporting: {md_file.name}")
        print(f"   UID: {uid}")
        print(f"   Pages: {info['pages_done']}/{pages_total}")

        md_content = export_full_markdown_from_uid(uid, api_key)

        if md_content:
            original_size = md_file.stat().st_size
            md_file.write_text(md_content, encoding="utf-8")

            meta_file = md_file.with_suffix(".meta.json")
            if meta_file.exists():
                meta_file.unlink()

            meta = ConversionMetadata(uid=uid, is_truncated=False)
            meta.save(md_file)

            new_size = len(md_content.encode("utf-8"))
            print(f"   ✅ Success: {original_size} → {new_size} bytes")
            success_count += 1
        else:
            print(f"   ❌ Failed")
            fail_count += 1

    print(f"\n📊 Complete: {success_count} success, {fail_count} failed")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
