from typing import List, Optional, Dict, Any, Callable

from rag.logger import get_logger
from kb_core.document_chunk_service import get_document_chunk_service

logger = get_logger(__name__)

from .vector_store import VectorStoreService

class ConsistencyService:
    """知识库一致性校验与修复服务"""

    @staticmethod
    def check(kb_id: str) -> Dict[str, Any]:
        """
        统一的一致性检查

        检查两个维度：
        1. 文档统计准确性：documents.chunk_count vs chunks 表实际数量
        2. 向量完整性：LanceDB 行数与文档统计的匹配情况

        Returns:
            {
                "kb_id": str,
                "status": str,  # "ok" | "issues_found"
                "summary": {
                    "doc_count": int,
                    "chunk_count_stored": int,  # documents.chunk_count 总和
                    "chunk_count_actual": int,  # chunks 表实际数量
                    "lance_rows": int,          # LanceDB 行数
                },
                "doc_stats": {
                    "accurate": bool,
                    "mismatched_count": int,
                    "issues": [...],
                },
                "vector_integrity": {
                    "status": str,  # "ok" | "missing" | "orphan" | "mismatch"
                    "missing_count": int,   # LanceDB 缺少的 chunk 数
                    "orphan_count": int,    # LanceDB 多余的 chunk 数
                    "issues": [...],
                },
                "recommendations": [...],  # 建议采取的行动
            }
        """
        from ..database import init_document_db, init_chunk_db

        doc_db = init_document_db()
        chunk_db = init_chunk_db()
        docs = doc_db.get_by_kb(kb_id)

        if not docs:
            return {
                "kb_id": kb_id,
                "status": "ok",
                "summary": {
                    "doc_count": 0,
                    "chunk_count_stored": 0,
                    "chunk_count_actual": 0,
                    "lance_rows": 0,
                },
                "doc_stats": {"accurate": True, "mismatched_count": 0, "issues": []},
                "vector_integrity": {
                    "status": "ok",
                    "missing_count": 0,
                    "orphan_count": 0,
                    "issues": [],
                },
                "recommendations": [],
            }

        chunk_count_stored = 0
        chunk_count_actual = 0
        doc_stats_issues = []

        for doc in docs:
            doc_id = doc.get("id")
            stored = doc.get("chunk_count", 0)
            actual = chunk_db.count_by_doc(doc_id)
            chunk_count_stored += stored
            chunk_count_actual += actual

            if stored != actual:
                diff = actual - stored
                doc_stats_issues.append(
                    {
                        "doc_id": doc_id,
                        "source_file": doc.get("source_file", ""),
                        "stored": stored,
                        "actual": actual,
                        "diff": diff,
                        "description": f"文档 {doc.get('source_file') or doc_id} 记录 {stored} chunks，实际 {actual} chunks (差异: {diff:+d})",
                    }
                )

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            stats = vs.get_stats()
            lance_rows = stats.get("row_count", 0) if stats.get("exists") else 0
        except Exception as e:
            logger.error(f"读取 LanceDB 失败: {e}")
            return {
                "kb_id": kb_id,
                "error": f"读取 LanceDB 失败: {e}",
                "status": "error",
            }

        missing_count = max(0, chunk_count_actual - lance_rows)
        orphan_count = max(0, lance_rows - chunk_count_actual)

        embedding_stats = chunk_db.get_embedding_stats(kb_id)
        emb_success = embedding_stats.get("success", 0)
        emb_pending = embedding_stats.get("pending", 0)
        emb_failed = embedding_stats.get("failed", 0)
        emb_total = embedding_stats.get("total", 0)

        vector_issues = []
        if missing_count > 0:
            vector_issues.append(
                {
                    "type": "missing",
                    "count": missing_count,
                    "description": f"LanceDB 缺少 {missing_count} 个 chunk（documents 记录存在但 LanceDB 没有）",
                }
            )
        if orphan_count > 0:
            if doc_stats_issues:
                vector_issues.append(
                    {
                        "type": "orphan_stats_error",
                        "count": orphan_count,
                        "description": f"LanceDB 比实际 chunk 总数多 {orphan_count} 个（同时存在统计错误，需先修正统计）",
                    }
                )
            else:
                vector_issues.append(
                    {
                        "type": "orphan_real",
                        "count": orphan_count,
                        "description": f"LanceDB 有 {orphan_count} 个 chunk 无法匹配到 documents 记录",
                    }
                )

        recommendations = []
        if doc_stats_issues:
            recommendations.append(
                {
                    "action": "fix_doc_stats",
                    "priority": "high",
                    "description": f"修正 {len(doc_stats_issues)} 个文档的 chunk_count 统计（安全操作，不删数据）",
                }
            )
        if missing_count > 0:
            recommendations.append(
                {
                    "action": "reimport",
                    "priority": "high",
                    "description": f"LanceDB 缺少 {missing_count} 个 chunk，需要重新导入相关文档",
                }
            )
        if orphan_count > 0 and not doc_stats_issues:
            recommendations.append(
                {
                    "action": "investigate",
                    "priority": "medium",
                    "description": f"存在 {orphan_count} 个无法匹配的 LanceDB 记录，需要人工确认",
                }
            )

        has_issues = len(doc_stats_issues) > 0 or missing_count > 0 or orphan_count > 0

        return {
            "kb_id": kb_id,
            "status": "issues_found" if has_issues else "ok",
            "summary": {
                "doc_count": len(docs),
                "chunk_count_stored": chunk_count_stored,
                "chunk_count_actual": chunk_count_actual,
                "lance_rows": lance_rows,
            },
            "doc_stats": {
                "accurate": len(doc_stats_issues) == 0,
                "mismatched_count": len(doc_stats_issues),
                "issues": doc_stats_issues,
            },
            "embedding_stats": {
                "total": emb_total,
                "success": emb_success,
                "pending": emb_pending,
                "failed": emb_failed,
                "in_lance": min(emb_success, lance_rows),
                "missing_in_lance": max(0, emb_success - lance_rows),
                "pending_not_in_lance": emb_pending,
                "failed_not_in_lance": emb_failed,
            },
            "vector_integrity": {
                "status": "ok"
                if not vector_issues
                else vector_issues[0].get("type", "unknown"),
                "missing_count": missing_count,
                "orphan_count": orphan_count,
                "issues": vector_issues,
            },
            "recommendations": recommendations,
        }

    @staticmethod
    def verify(kb_id: str) -> Dict[str, Any]:
        """
        校验知识库一致性（兼容旧接口）

        比较 chunks 表中的实际 chunk 总数与 LanceDB 实际行数。
        """
        from ..database import init_document_db, init_chunk_db

        doc_db = init_document_db()
        chunk_db = init_chunk_db()
        docs = doc_db.get_by_kb(kb_id)
        doc_files = len(docs)
        doc_chunks = sum(d.get("chunk_count", 0) for d in docs)

        actual_chunks = sum(chunk_db.count_by_doc(d.get("id")) for d in docs)

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            stats = vs.get_stats()
            lance_rows = stats.get("row_count", 0) if stats.get("exists") else 0
        except Exception as e:
            logger.error(f"读取 LanceDB 失败: {e}")
            return {
                "kb_id": kb_id,
                "error": f"读取 LanceDB 失败: {e}",
                "status": "error",
            }

        missing_chunks = max(0, actual_chunks - lance_rows)
        orphan_rows = max(0, lance_rows - actual_chunks)
        consistent = missing_chunks == 0 and orphan_rows == 0

        if consistent:
            status = "consistent"
        elif missing_chunks > 0 and orphan_rows > 0:
            status = "mixed_inconsistency"
        elif missing_chunks > 0:
            status = "missing_data"
        else:
            status = "orphan_data"

        return {
            "kb_id": kb_id,
            "doc_files": doc_files,
            "doc_chunks": doc_chunks,
            "actual_chunks": actual_chunks,
            "lance_rows": lance_rows,
            "consistent": consistent,
            "missing_chunks": missing_chunks,
            "orphan_rows": orphan_rows,
            "status": status,
        }

    @staticmethod
    def verify_doc_stats(kb_id: str) -> Dict[str, Any]:
        """
        校验文档级别的 chunk_count 准确性

        比较每个文档的 documents.chunk_count 与 chunks 表中的实际数量。
        不修改任何数据，只报告问题。
        """
        from ..database import init_document_db, init_chunk_db

        doc_db = init_document_db()
        chunk_db = init_chunk_db()

        docs = doc_db.get_by_kb(kb_id)
        mismatched_docs = []
        total_stored_count = 0
        total_actual_count = 0

        for doc in docs:
            doc_id = doc.get("id")
            stored_count = doc.get("chunk_count", 0)
            actual_count = chunk_db.count_by_doc(doc_id)

            total_stored_count += stored_count
            total_actual_count += actual_count

            if stored_count != actual_count:
                mismatched_docs.append(
                    {
                        "doc_id": doc_id,
                        "source_file": doc.get("source_file", ""),
                        "stored_count": stored_count,
                        "actual_count": actual_count,
                        "diff": actual_count - stored_count,
                    }
                )

        return {
            "kb_id": kb_id,
            "total_documents": len(docs),
            "mismatched_count": len(mismatched_docs),
            "total_stored_count": total_stored_count,
            "total_actual_count": total_actual_count,
            "mismatched_docs": mismatched_docs,
            "is_accurate": len(mismatched_docs) == 0,
        }

    @staticmethod
    def fix_doc_stats(kb_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        修复文档的 chunk_count 和 total_chars 统计信息

        此方法只更新 documents 表的统计字段，不涉及任何数据删除。
        通过查询 chunks 表的实际数量来更新统计值。

        Args:
            kb_id: 知识库 ID
            dry_run: 如果为 True，只报告会做什么，不实际执行修改

        Returns:
            {
                "kb_id": str,
                "mode": str,
                "fixed": int,
                "skipped": int,
                "details": [...],
            }
        """
        from ..database import init_document_db
        from ..document_chunk_service import get_document_chunk_service

        doc_db = init_document_db()
        docs = doc_db.get_by_kb(kb_id)

        if not docs:
            return {
                "kb_id": kb_id,
                "mode": "fix_stats",
                "fixed": 0,
                "skipped": 0,
                "message": "没有文档需要修复",
            }

        service = get_document_chunk_service(kb_id=kb_id)
        fixed = 0
        skipped = 0
        details = []

        for doc in docs:
            doc_id = doc.get("id")
            stored_count = doc.get("chunk_count", 0)

            if dry_run:
                from ..database import init_chunk_db

                chunk_db = init_chunk_db()
                actual_count = chunk_db.count_by_doc(doc_id)
                if stored_count != actual_count:
                    details.append(
                        {
                            "doc_id": doc_id,
                            "source_file": doc.get("source_file", ""),
                            "stored_count": stored_count,
                            "actual_count": actual_count,
                            "action": "would_fix",
                        }
                    )
                else:
                    skipped += 1
            else:
                success = service.update_document_stats(doc_id)
                if success:
                    fixed += 1
                    details.append(
                        {
                            "doc_id": doc_id,
                            "source_file": doc.get("source_file", ""),
                            "stored_count": stored_count,
                            "action": "fixed",
                        }
                    )
                else:
                    skipped += 1
                    details.append(
                        {
                            "doc_id": doc_id,
                            "source_file": doc.get("source_file", ""),
                            "action": "failed",
                        }
                    )

        return {
            "kb_id": kb_id,
            "mode": "fix_stats",
            "dry_run": dry_run,
            "fixed": fixed,
            "skipped": skipped,
            "message": f"修复完成: {fixed} 个文档已更新, {skipped} 个跳过",
            "details": details,
        }

    @staticmethod
    def repair(kb_id: str) -> Dict[str, Any]:
        """
        修复知识库统计信息

        注意：此方法仅修正 documents 表的 chunk_count 统计（安全操作，不删数据）。
        对于实际的 orphans 或 missing chunks，需要手动处理或重新导入相关文档。
        """
        return ConsistencyService.fix_doc_stats(kb_id)

    @staticmethod
    def get_embedding_stats(kb_id: str) -> Dict[str, Any]:
        """
        获取 chunk 向量化统计信息

        Returns:
            {
                "kb_id": str,
                "total": int,        # 总 chunk 数
                "success": int,      # 成功向量化的 chunk 数 (embedding_generated=1)
                "failed": int,       # 向量化失败的 chunk 数 (embedding_generated=2)
                "pending": int,      # 等待向量化的 chunk 数 (embedding_generated=0)
                "lance_rows": int,   # LanceDB 实际行数
                "missing_count": int,  # LanceDB 缺少的数量
                "orphan_count": int,   # LanceDB 多余的数量
            }
        """
        from ..database import init_chunk_db

        chunk_db = init_chunk_db()
        stats = chunk_db.get_embedding_stats(kb_id)

        try:
            vs = VectorStoreService.get_vector_store(kb_id)
            lance_stats = vs.get_stats()
            lance_rows = (
                lance_stats.get("row_count", 0) if lance_stats.get("exists") else 0
            )
        except Exception:
            lance_rows = 0

        chunk_count_actual = stats["total"]
        missing_count = max(0, chunk_count_actual - lance_rows)
        orphan_count = max(0, lance_rows - chunk_count_actual)

        return {
            "kb_id": kb_id,
            "total": stats["total"],
            "success": stats["success"],
            "failed": stats["failed"],
            "pending": stats["pending"],
            "lance_rows": lance_rows,
            "missing_count": missing_count,
            "orphan_count": orphan_count,
        }

    @staticmethod
    def safe_delete_files(kb_id: str, sources: List[str]) -> Dict[str, Any]:
        """
        原子性删除文件（保证 documents 和 LanceDB 一致）

        Args:
            kb_id: 知识库 ID
            sources: 要删除的源文件路径列表

        Returns:
            {
                "kb_id": str,
                "deleted_sources": int,
                "deleted_vectors": int,
                "success": bool,
                "message": str,
            }
        """
        if not sources:
            return {
                "kb_id": kb_id,
                "deleted_sources": 0,
                "deleted_vectors": 0,
                "success": True,
                "message": "没有文件需要删除",
            }

        from ..database import init_document_db

        doc_db = init_document_db()

        deleted_sources = 0
        deleted_vectors = 0
        for source in sources:
            try:
                doc = doc_db.get_by_source_path(kb_id, source)
                if doc:
                    doc_id = doc.get("id")
                    if doc_id:
                        from ..document_chunk_service import (
                            DocumentChunkService,
                        )

                        svc = DocumentChunkService(kb_id)
                        result = svc.delete_document_cascade(doc_id, delete_lance=True)
                        deleted_sources += 1
                        deleted_vectors += result.get("lance", 0)
            except Exception as e:
                logger.warning(f"删除文档记录失败 {source}: {e}")

        verify = ConsistencyService.verify(kb_id)
        consistent = verify.get("consistent", False)

        return {
            "kb_id": kb_id,
            "deleted_sources": deleted_sources,
            "deleted_vectors": deleted_vectors,
            "success": consistent,
            "message": "删除成功"
            if consistent
            else f"删除完成但存在不一致 (missing={verify.get('missing_chunks')})",
        }

    @staticmethod
    def repair_all() -> Dict[str, Any]:
        """
        修复所有知识库的一致性

        Returns:
            {
                "total": int,
                "repaired": int,
                "failed": int,
                "results": list,
            }
        """
        from kb_core.registry import KnowledgeBaseRegistry

        registry = KnowledgeBaseRegistry()
        kbs = registry.list()

        results = []
        repaired = 0
        failed = 0

        for kb in kbs:
            kb_id = kb.id
            try:
                result = ConsistencyService.repair(kb_id)
                results.append(result)
                if result.get("fixed", 0) > 0:
                    repaired += 1
            except Exception as e:
                logger.error(f"修复知识库 {kb_id} 失败: {e}")
                results.append(
                    {
                        "kb_id": kb_id,
                        "repaired": False,
                        "message": str(e),
                    }
                )
                failed += 1

        return {
            "total": len(kbs),
            "repaired": repaired,
            "failed": failed,
            "results": results,
        }

    @staticmethod
    def get_doc_embedding_stats(kb_id: str) -> List[Dict[str, Any]]:
        """获取每个文档的向量统计
        
        实际检查 LanceDB，获取每个文档的向量生成状态。
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            文档向量统计列表
        """
        from ..database import init_chunk_db

        return init_chunk_db().get_doc_embedding_stats(kb_id)

    @staticmethod
    def check_and_mark_failed(kb_id: str) -> Dict[str, Any]:
        """检查并标记向量生成失败的 chunks
        
        检查所有 chunk 是否存在于 LanceDB，将不存在的标记为失败。
        
        Args:
            kb_id: 知识库 ID
            
        Returns:
            检查结果统计
        """
        from ..database import init_chunk_db

        chunk_db = init_chunk_db()
        result = chunk_db.mark_chunks_missing_from_lance(kb_id)
        return {
            "kb_id": kb_id,
            "marked_failed": result["marked_failed"],
            "total_checked": result["total_checked"],
            "message": f"已标记 {result['marked_failed']} 个 chunk 为失败（检查了 {result['total_checked']} 个）",
        }
