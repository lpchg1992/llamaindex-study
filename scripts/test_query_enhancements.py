#!/usr/bin/env python3
"""
Query Enhancement Test Script

Tests all combinations of:
- Enhancement options: None, HyDE, MultiQuery, AutoMerging, HyDE+MultiQuery, HyDE+AutoMerging, MultiQuery+AutoMerging, All
- LLM modes: siliconflow, ollama
"""

import requests
import time
import json
from typing import Dict, Any, List, Optional

BASE_URL = "http://localhost:37241"
TIMEOUT = 180  # 3 minutes per test


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"


def print_header(text: str):
    print(f"\n{'=' * 60}")
    print(f"{Colors.BLUE}{text}{Colors.RESET}")
    print(f"{'=' * 60}")


def print_result(name: str, result: Dict[str, Any], duration: float, success: bool):
    status = (
        f"{Colors.GREEN}✓ PASS{Colors.RESET}"
        if success
        else f"{Colors.RED}✗ FAIL{Colors.RESET}"
    )
    print(f"  {status} | {duration:>6.2f}s | {name}")
    if not success:
        print(
            f"       Error: {result.get('detail', result.get('response', 'Unknown error'))[:100]}"
        )
    return success


def test_query(
    query: str,
    kb_id: str,
    llm_mode: Optional[str] = None,
    use_hyde: bool = False,
    use_multi_query: bool = False,
    use_auto_merging: bool = False,
) -> Dict[str, Any]:
    """Test a single query configuration"""
    payload = {
        "query": query,
        "kb_ids": kb_id,
        "top_k": 3,
        "route_mode": "general",
        "use_hyde": use_hyde,
        "use_multi_query": use_multi_query,
        "use_auto_merging": use_auto_merging,
    }
    if llm_mode:
        payload["llm_mode"] = llm_mode

    start = time.time()
    try:
        resp = requests.post(
            f"{BASE_URL}/query",
            json=payload,
            timeout=TIMEOUT,
        )
        duration = time.time() - start

        if resp.status_code == 200:
            result = resp.json()
            result["_duration"] = duration
            result["_success"] = True
            return result
        else:
            return {
                "_success": False,
                "_duration": duration,
                "detail": f"HTTP {resp.status_code}: {resp.text[:200]}",
            }
    except requests.exceptions.Timeout:
        return {
            "_success": False,
            "_duration": time.time() - start,
            "detail": "Request timeout",
        }
    except Exception as e:
        return {
            "_success": False,
            "_duration": time.time() - start,
            "detail": str(e),
        }


def get_knowledge_bases() -> List[Dict[str, Any]]:
    """Get list of available knowledge bases"""
    try:
        resp = requests.get(f"{BASE_URL}/kbs", timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Failed to get knowledge bases: {e}")
    return []


def run_tests():
    print_header("Query Enhancement Test Suite")

    kbs = get_knowledge_bases()
    if not kbs:
        print(f"{Colors.RED}No knowledge bases found!{Colors.RESET}")
        return

    print(f"\nFound {len(kbs)} knowledge bases:")
    for kb in kbs:
        print(f"  - {kb['id']}: {kb['name']} ({kb['row_count']} rows)")

    test_kb = kbs[0]["id"]
    test_query_text = "这个项目的背景和目标是什么？"

    enhancement_configs = [
        {
            "name": "Baseline (no enhancement)",
            "use_hyde": False,
            "use_multi_query": False,
            "use_auto_merging": False,
        },
        {
            "name": "HyDE only",
            "use_hyde": True,
            "use_multi_query": False,
            "use_auto_merging": False,
        },
        {
            "name": "MultiQuery only",
            "use_hyde": False,
            "use_multi_query": True,
            "use_auto_merging": False,
        },
        {
            "name": "AutoMerging only",
            "use_hyde": False,
            "use_multi_query": False,
            "use_auto_merging": True,
        },
        {
            "name": "HyDE + MultiQuery",
            "use_hyde": True,
            "use_multi_query": True,
            "use_auto_merging": False,
        },
        {
            "name": "HyDE + AutoMerging",
            "use_hyde": True,
            "use_multi_query": False,
            "use_auto_merging": True,
        },
        {
            "name": "MultiQuery + AutoMerging",
            "use_hyde": False,
            "use_multi_query": True,
            "use_auto_merging": True,
        },
        {
            "name": "All enhancements (HyDE + MultiQuery + AutoMerging)",
            "use_hyde": True,
            "use_multi_query": True,
            "use_auto_merging": True,
        },
    ]

    llm_modes = [
        {"name": "siliconflow (DeepSeek)", "llm_mode": None},
        {"name": "ollama (local)", "llm_mode": "ollama"},
    ]

    all_results = []

    for llm in llm_modes:
        print_header(f"Testing LLM: {llm['name']}")

        for config in enhancement_configs:
            name = f"{config['name']}"
            result = test_query(
                query=test_query_text,
                kb_id=test_kb,
                llm_mode=llm["llm_mode"],
                use_hyde=config["use_hyde"],
                use_multi_query=config["use_multi_query"],
                use_auto_merging=config["use_auto_merging"],
            )

            success = result.get("_success", False)
            duration = result.get("_duration", 0)
            sources_count = len(result.get("sources", []))

            print_result(name, result, duration, success)

            if success:
                print(f"       Sources: {sources_count}")
                response_preview = result.get("response", "")[:80]
                print(f"       Response: {response_preview}...")

            all_results.append(
                {
                    "llm": llm["name"],
                    "config": config["name"],
                    "success": success,
                    "duration": duration,
                    "sources": sources_count,
                }
            )

            time.sleep(1)

    print_header("Test Summary")

    print(f"\n{'LLM Mode':<30} {'Config':<45} {'Status':<10} {'Time':<10} {'Sources'}")
    print("-" * 110)

    for r in all_results:
        status = (
            f"{Colors.GREEN}PASS{Colors.RESET}"
            if r["success"]
            else f"{Colors.RED}FAIL{Colors.RESET}"
        )
        print(
            f"{r['llm']:<30} {r['config']:<45} {status:<10} {r['duration']:>6.2f}s   {r['sources']}"
        )

    passed = sum(1 for r in all_results if r["success"])
    total = len(all_results)
    print(f"\n{Colors.GREEN}Passed: {passed}/{total}{Colors.RESET}")

    if passed < total:
        print(f"\n{Colors.YELLOW}Failed tests:{Colors.RESET}")
        for r in all_results:
            if not r["success"]:
                print(f"  - {r['llm']} + {r['config']}")


if __name__ == "__main__":
    run_tests()
