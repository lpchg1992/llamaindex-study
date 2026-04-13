"""
Unified document and chunk management service.
CRUD for documents/chunks with cascade sync to LanceDB and Dedup.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from llamaindex_study.logger import get_logger

logger = get_logger(__name__)


class DocumentChunkService:
    """Manages documents/chunks tables with cascade operations.

    Provides CRUD operations for documents and their chunks, with automatic
    sync to LanceDB vector store. Supports cascade delete of documents
    and their associated chunks/vectors.

    Args:
        kb_id: Knowledge base identifier
        persist_dir: Optional persistence directory path
    """

    def __init__(self, kb_id: str, persist_dir: Optional[Path] = None):
        self.kb_id = kb_id
        self.persist_dir = persist_dir
        self._doc_db = None
        self._chunk_db = None

    def _get_doc_db(self):
        if self._doc_db is None:
            from kb.database import init_document_db

            self._doc_db = init_document_db()
        return self._doc_db

    def _get_chunk_db(self):
        if self._chunk_db is None:
            from kb.database import init_chunk_db

            self._chunk_db = init_chunk_db()
        return self._chunk_db

    def create_document(
        self,
        source_file: str,
        source_path: str,
        file_hash: str,
        nodes: List[Any],
        file_size: int = 0,
        doc_id: Optional[str] = None,
        zotero_doc_id: Optional[str] = None,
        failed_node_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a document record and its associated chunk records.

        Args:
            source_file: Original filename
            source_path: Full path to source file
            file_hash: MD5 hash of the source file
            nodes: List of parsed LlamaIndex nodes
            file_size: Size of source file in bytes
            doc_id: Optional explicit document ID
            zotero_doc_id: Zotero document ID if applicable
            failed_node_ids: List of node IDs that failed embedding

        Returns:
            Created document dict or None if failed
        """
        if not nodes:
            logger.warning(f"[{self.kb_id}] create_document: empty nodes, skipping")
            return None

        failed_set = set(failed_node_ids or [])

        try:
            doc_db = self._get_doc_db()
            chunk_db = self._get_chunk_db()

            total_chars = sum(
                len(node.get_content())
                if hasattr(node, "get_content")
                else len(str(node))
                for node in nodes
            )

            doc = doc_db.create(
                kb_id=self.kb_id,
                source_file=source_file,
                source_path=source_path,
                file_hash=file_hash,
                file_size=file_size,
                doc_id=doc_id,
                zotero_doc_id=zotero_doc_id,
            )
            created_doc_id = doc["id"]

            chunks = []
            for idx, node in enumerate(nodes):
                metadata = node.metadata if hasattr(node, "metadata") else {}
                parent_id = metadata.get("parent_doc_id") or metadata.get("parent_id")
                hierarchy_level = (
                    metadata.get("hierarchy_level") or metadata.get("level") or 0
                )

                metadata = {}
                if hasattr(node, "metadata") and node.metadata:
                    if isinstance(node.metadata, dict):
                        metadata = node.metadata
                    else:
                        try:
                            metadata = json.loads(node.metadata)
                        except Exception:
                            metadata = {}

                node_id = (
                    node.node_id
                    if hasattr(node, "node_id")
                    else (node.id_ if hasattr(node, "id_") else f"chunk_{idx}")
                )

                if node_id in failed_set:
                    emb_status = 2
                elif hasattr(node, "embedding") and node.embedding and not all(v == 0.0 for v in node.embedding):
                    emb_status = 1
                else:
                    emb_status = 0

                chunk = {
                    "id": node_id,
                    "doc_id": created_doc_id,
                    "kb_id": self.kb_id,
                    "text": node.get_content()
                    if hasattr(node, "get_content")
                    else str(node),
                    "text_length": len(node.get_content())
                    if hasattr(node, "get_content")
                    else len(str(node)),
                    "chunk_index": idx,
                    "parent_chunk_id": parent_id,
                    "hierarchy_level": hierarchy_level,
                    "metadata": metadata,
                    "embedding_generated": emb_status,
                }
                chunks.append(chunk)

            if chunks:
                chunk_db.create_bulk(chunks)

            doc_db.update_stats(
                created_doc_id, chunk_count=len(chunks), total_chars=total_chars
            )

            logger.info(
                f"[{self.kb_id}] Created doc {created_doc_id}: {len(chunks)} chunks, {total_chars} chars"
            )
            return doc

        except Exception as e:
            logger.error(f"[{self.kb_id}] create_document failed: {e}", exc_info=True)
            return None

    def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get a document by ID.

        Args:
            doc_id: Document ID

        Returns:
            Document dict or None if not found
        """
        try:
            return self._get_doc_db().get(doc_id)
        except Exception as e:
            logger.error(f"[{self.kb_id}] get_document failed: {e}")
            return None

    def get_document_chunks(self, doc_id: str) -> List[Dict[str, Any]]:
        """Get all chunks belonging to a document.

        Args:
            doc_id: Document ID

        Returns:
            List of chunk dicts
        """
        try:
            return self._get_chunk_db().get_by_doc(doc_id)
        except Exception as e:
            logger.error(f"[{self.kb_id}] get_document_chunks failed: {e}")
            return []

    def get_all_documents(self) -> List[Dict[str, Any]]:
        try:
            return self._get_doc_db().get_by_kb(self.kb_id)
        except Exception as e:
            logger.error(f"[{self.kb_id}] get_all_documents failed: {e}")
            return []

    def delete_document_cascade(
        self,
        doc_id: str,
        delete_lance: bool = True,
    ) -> Dict[str, int]:
        """Delete a document and all its associated chunks and vectors.

        Args:
            doc_id: Document ID to delete
            delete_lance: Whether to also delete LanceDB vector records

        Returns:
            Dict with counts of deleted chunks, lance records, and documents
        """
        result = {"chunks": 0, "lance": 0, "documents": 0}

        try:
            doc_db = self._get_doc_db()
            chunk_db = self._get_chunk_db()

            doc = doc_db.get(doc_id)
            if not doc:
                logger.warning(
                    f"[{self.kb_id}] delete_document_cascade: doc {doc_id} not found"
                )
                return result

            try:
                result["chunks"] = chunk_db.delete_by_doc(doc_id)
                logger.info(
                    f"[{self.kb_id}] Deleted {result['chunks']} chunks for doc_id={doc_id}"
                )
            except Exception as e:
                logger.error(f"[{self.kb_id}] Delete chunks failed: {e}")

            try:
                if doc_db.delete(doc_id):
                    result["documents"] = 1
                    logger.info(f"[{self.kb_id}] Deleted doc {doc_id}")
            except Exception as e:
                logger.error(f"[{self.kb_id}] Delete doc failed: {e}")

            if delete_lance:
                try:
                    from kb.lance_crud import LanceCRUDService

                    result["lance"] = LanceCRUDService.delete_by_doc_ids(
                        self.kb_id, [doc_id]
                    )
                    logger.info(
                        f"[{self.kb_id}] Deleted {result['lance']} LanceDB records"
                    )
                except Exception as e:
                    logger.error(f"[{self.kb_id}] Delete LanceDB failed: {e}")

            logger.info(f"[{self.kb_id}] delete_document_cascade completed: {result}")
            return result

        except Exception as e:
            logger.error(
                f"[{self.kb_id}] delete_document_cascade failed: {e}", exc_info=True
            )
            return result

    def delete_documents_by_source(
        self, source_file: str, delete_lance: bool = True
    ) -> Dict[str, int]:
        """Delete all documents matching a source file pattern.

        Args:
            source_file: Source file name or path to match
            delete_lance: Whether to also delete LanceDB vector records

        Returns:
            Dict with counts of deleted documents, chunks, and lance records
        """
        result = {"documents": 0, "chunks": 0, "lance": 0}

        try:
            all_docs = self.get_all_documents()
            matching_docs = [
                doc
                for doc in all_docs
                if source_file in doc.get("source_path", "")
                or source_file in doc.get("source_file", "")
            ]

            for doc in matching_docs:
                cascade_result = self.delete_document_cascade(
                    doc["id"], delete_lance=delete_lance
                )
                result["documents"] += cascade_result.get("documents", 0)
                result["chunks"] += cascade_result.get("chunks", 0)
                result["lance"] += cascade_result.get("lance", 0)

            return result

        except Exception as e:
            logger.error(
                f"[{self.kb_id}] delete_documents_by_source failed: {e}", exc_info=True
            )
            return result

    def update_document_stats(self, doc_id: str) -> bool:
        try:
            chunk_db = self._get_chunk_db()
            chunks = chunk_db.get_by_doc(doc_id)
            chunk_count = len(chunks)
            total_chars = sum(c.get("text_length", 0) for c in chunks)
            return self._get_doc_db().update_stats(doc_id, chunk_count, total_chars)
        except Exception as e:
            logger.error(f"[{self.kb_id}] update_document_stats failed: {e}")
            return False

    def mark_chunks_failed(self, chunk_ids: List[str]) -> int:
        if not chunk_ids:
            return 0
        try:
            chunk_db = self._get_chunk_db()
            return chunk_db.mark_failed_bulk(chunk_ids)
        except Exception as e:
            logger.error(f"[{self.kb_id}] mark_chunks_failed failed: {e}")
            return 0

    def get_stats(self) -> Dict[str, int]:
        try:
            doc_db = self._get_doc_db()
            stats = doc_db.get_stats(self.kb_id)
            return {
                "document_count": stats.get("document_count", 0),
                "total_chunks": stats.get("total_chunks", 0),
            }
        except Exception as e:
            logger.error(f"[{self.kb_id}] get_stats failed: {e}")
            return {"document_count": 0, "total_chunks": 0}

    def rebuild_from_lance(
        self, force: bool = False, batch_size: int = 500
    ) -> Dict[str, int]:
        from kb.lance_crud import LanceCRUDService

        result = {"documents": 0, "chunks": 0}

        try:
            doc_db = self._get_doc_db()
            chunk_db = self._get_chunk_db()

            if not force:
                existing = doc_db.get_by_kb(self.kb_id)
                if existing:
                    logger.info(
                        f"[{self.kb_id}] rebuild_from_lance: already has {len(existing)} docs, skipping"
                    )
                    return result

            doc_ids = LanceCRUDService.get_doc_ids(self.kb_id)
            logger.info(
                f"[{self.kb_id}] rebuild_from_lance: found {len(doc_ids)} doc_ids"
            )

            for doc_id in doc_ids:
                try:
                    nodes = LanceCRUDService.query_nodes(
                        self.kb_id, doc_id=doc_id, limit=99999
                    )
                    if not nodes:
                        continue

                    first_node = nodes[0]
                    metadata = first_node.metadata or {}

                    source_path = ""
                    source_file = doc_id
                    try:
                        if "_node_content" in metadata:
                            node_data = json.loads(metadata["_node_content"])
                            relationships = node_data.get("relationships", {})
                            for key, rel in relationships.items():
                                if key.isdigit() and key == "1":
                                    source_path = rel.get("metadata", {}).get(
                                        "file_path", ""
                                    )
                                    source_file = (
                                        Path(source_path).name
                                        if source_path
                                        else doc_id
                                    )
                                    break
                    except Exception:
                        pass

                    file_hash = metadata.get("file_hash", "")

                    doc = doc_db.create(
                        kb_id=self.kb_id,
                        doc_id=doc_id,
                        source_file=source_file,
                        source_path=source_path,
                        file_hash=file_hash,
                        file_size=0,
                    )

                    chunks = []
                    for idx, node in enumerate(nodes):
                        parent_id = None
                        hierarchy_level = 0
                        try:
                            if "_node_content" in node.metadata:
                                node_data = json.loads(node.metadata["_node_content"])
                                relationships = node_data.get("relationships", {})
                                for key, rel in relationships.items():
                                    if key.isdigit() and key != "1":
                                        parent_id = rel.get("node_id")
                                        break
                                hierarchy_level = 0
                                if "2" in relationships:
                                    hierarchy_level = 1
                                elif "3" in relationships:
                                    hierarchy_level = 2
                        except Exception:
                            pass

                        chunk = {
                            "id": node.id,
                            "doc_id": doc_id,
                            "kb_id": self.kb_id,
                            "text": node.text,
                            "text_length": node.text_length,
                            "chunk_index": idx,
                            "parent_chunk_id": parent_id,
                            "hierarchy_level": hierarchy_level,
                            "metadata": node.metadata,
                            "embedding_generated": 1,
                        }
                        chunks.append(chunk)

                    if chunks:
                        chunk_db.create_bulk(chunks)
                        result["chunks"] += len(chunks)
                        doc_db.update_stats(doc_id, chunk_count=len(chunks))

                    result["documents"] += 1

                except Exception as e:
                    logger.warning(f"[{self.kb_id}] Rebuild doc {doc_id} failed: {e}")
                    continue

            logger.info(f"[{self.kb_id}] rebuild_from_lance completed: {result}")
            return result

        except Exception as e:
            logger.error(
                f"[{self.kb_id}] rebuild_from_lance failed: {e}", exc_info=True
            )
            return result

    def delete_chunk_cascade(
        self,
        chunk_id: str,
        cascade_children: bool = True,
        delete_lance: bool = True,
    ) -> Dict[str, int]:
        result = {"chunks": 0, "lance": 0, "children_orphaned": 0}

        try:
            chunk_db = self._get_chunk_db()
            doc_db = self._get_doc_db()

            chunk = chunk_db.get(chunk_id)
            if not chunk:
                logger.warning(
                    f"[{self.kb_id}] delete_chunk_cascade: chunk {chunk_id} not found"
                )
                return result

            doc_id = chunk.get("doc_id")

            all_chunks = chunk_db.get_by_doc(doc_id)
            child_chunks = [
                c for c in all_chunks if c.get("parent_chunk_id") == chunk_id
            ]

            if cascade_children and child_chunks:
                for child in child_chunks:
                    child_result = self.delete_chunk_cascade(
                        child["id"],
                        cascade_children=True,
                        delete_lance=delete_lance,
                    )
                    result["chunks"] += child_result.get("chunks", 0)
                    result["lance"] += child_result.get("lance", 0)
                    result["children_orphaned"] += child_result.get(
                        "children_orphaned", 0
                    )
            elif child_chunks:
                for child in child_chunks:
                    try:
                        chunk_db.update_parent(child["id"], None)
                        result["children_orphaned"] += 1
                    except Exception as e:
                        logger.warning(
                            f"[{self.kb_id}] Failed to orphan child chunk {child['id']}: {e}"
                        )

            if chunk_db.delete(chunk_id):
                result["chunks"] = 1

            if delete_lance:
                try:
                    from kb.lance_crud import LanceCRUDService

                    result["lance"] = LanceCRUDService.delete_by_chunk_ids(
                        self.kb_id, [chunk_id]
                    )
                except Exception as e:
                    logger.error(f"[{self.kb_id}] Delete LanceDB chunk failed: {e}")

            if doc_id:
                self.update_document_stats(doc_id)

            logger.info(
                f"[{self.kb_id}] delete_chunk_cascade({chunk_id}) completed: {result}"
            )
            return result

        except Exception as e:
            logger.error(
                f"[{self.kb_id}] delete_chunk_cascade failed: {e}", exc_info=True
            )
            return result

    def get_chunk_children(self, chunk_id: str) -> List[Dict[str, Any]]:
        """Get all child chunks of a given chunk (for hierarchy traversal).

        Args:
            chunk_id: Parent chunk ID

        Returns:
            List of child chunk dicts
        """
        try:
            chunk_db = self._get_chunk_db()
            chunk = chunk_db.get(chunk_id)
            if not chunk:
                return []
            doc_id = chunk.get("doc_id")
            if not doc_id:
                return []
            all_chunks = chunk_db.get_by_doc(doc_id)
            return [c for c in all_chunks if c.get("parent_chunk_id") == chunk_id]
        except Exception as e:
            logger.error(f"[{self.kb_id}] get_chunk_children failed: {e}")
            return []


def get_document_chunk_service(
    kb_id: str, persist_dir: Optional[Path] = None
) -> DocumentChunkService:
    """Factory function to create a DocumentChunkService instance.

    Args:
        kb_id: Knowledge base identifier
        persist_dir: Optional persistence directory path

    Returns:
        DocumentChunkService instance
    """
    return DocumentChunkService(kb_id=kb_id, persist_dir=persist_dir)
