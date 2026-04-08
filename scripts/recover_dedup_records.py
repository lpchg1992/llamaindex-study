"""
Recover dedup_records from documents table.

This script rebuilds the dedup_records table from the documents table,
recomputing file hashes when source files are available.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import hashlib
import time
from kb.database import get_db
from sqlalchemy import text


def compute_file_hash(file_path: str) -> str:
    """Compute MD5 hash of a file."""
    try:
        hasher = hashlib.md5()
        with open(file_path, "rb") as f:
            # Read up to 1MB for quick hash
            chunk = f.read(1024 * 1024)
            hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"  Warning: Could not compute hash for {file_path}: {e}")
        return ""


def recover_dedup_records(kb_id: str = None, dry_run: bool = False):
    """
    Recover dedup_records from documents table.

    Args:
        kb_id: Specific knowledge base to recover, or None for all
        dry_run: If True, only show what would be done without making changes
    """
    db = get_db()

    # Build query
    if kb_id:
        query = text("""
            SELECT id, kb_id, source_file, source_path, file_hash, 
                   chunk_count, created_at, updated_at
            FROM documents 
            WHERE kb_id = :kb_id
        """)
        params = {"kb_id": kb_id}
    else:
        query = text("""
            SELECT id, kb_id, source_file, source_path, file_hash, 
                   chunk_count, created_at, updated_at
            FROM documents
        """)
        params = {}

    recovered = 0
    skipped = 0
    errors = 0

    with db.session_scope() as session:
        result = session.execute(query, params)
        rows = result.fetchall()

    print(f"\nFound {len(rows)} documents to process")
    print(f"Dry run: {dry_run}\n")

    for row in rows:
        doc_id = row[0]
        doc_kb_id = row[1]
        source_file = row[2]
        source_path = row[3]
        existing_hash = row[4] or ""
        chunk_count = row[5]
        created_at = row[6]
        updated_at = row[7]

        # Determine the file path to use
        # Use source_path if available, otherwise construct from source_file
        file_path = source_path if source_path else source_file

        # Compute hash if source file exists and existing hash is empty
        if not existing_hash:
            if source_path and Path(source_path).exists():
                file_hash = compute_file_hash(source_path)
            else:
                file_hash = ""
                print(f"  Warning: Source file not found for {doc_id}: {source_path}")
        else:
            file_hash = existing_hash

        # Prepare dedup_record data
        now = time.time()
        mtime = updated_at if updated_at else created_at
        last_processed = updated_at if updated_at else created_at

        if dry_run:
            print(
                f"  [DRY RUN] Would insert: kb_id={doc_kb_id}, file_path={file_path[:50]}..., hash={file_hash[:8] if file_hash else 'empty'}..."
            )
        else:
            try:
                with db.session_scope() as session:
                    # Check if record already exists
                    existing = session.execute(
                        text("""
                            SELECT id FROM dedup_records 
                            WHERE kb_id = :kb_id AND file_path = :file_path
                        """),
                        {"kb_id": doc_kb_id, "file_path": file_path},
                    ).fetchone()

                    if existing:
                        # Update existing
                        session.execute(
                            text("""
                                UPDATE dedup_records 
                                SET hash = :hash, doc_id = :doc_id, 
                                    chunk_count = :chunk_count,
                                    mtime = :mtime,
                                    last_processed = :last_processed,
                                    updated_at = :now
                                WHERE kb_id = :kb_id AND file_path = :file_path
                            """),
                            {
                                "kb_id": doc_kb_id,
                                "file_path": file_path,
                                "hash": file_hash,
                                "doc_id": doc_id,
                                "chunk_count": chunk_count,
                                "mtime": mtime,
                                "last_processed": last_processed,
                                "now": now,
                            },
                        )
                    else:
                        # Insert new
                        session.execute(
                            text("""
                                INSERT INTO dedup_records 
                                (kb_id, file_path, hash, doc_id, chunk_count, 
                                 mtime, last_processed, created_at, updated_at)
                                VALUES 
                                (:kb_id, :file_path, :hash, :doc_id, :chunk_count,
                                 :mtime, :last_processed, :created_at, :updated_at)
                            """),
                            {
                                "kb_id": doc_kb_id,
                                "file_path": file_path,
                                "hash": file_hash,
                                "doc_id": doc_id,
                                "chunk_count": chunk_count,
                                "mtime": mtime,
                                "last_processed": last_processed,
                                "created_at": now,
                                "updated_at": now,
                            },
                        )
                recovered += 1
                if recovered % 20 == 0:
                    print(f"  Processed {recovered} records...")
            except Exception as e:
                errors += 1
                print(f"  Error inserting {doc_id}: {e}")

    print(f"\n=== Recovery Complete ===")
    print(f"Recovered: {recovered}")
    print(f"Errors: {errors}")

    return recovered, errors


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Recover dedup_records from documents table"
    )
    parser.add_argument(
        "--kb-id", type=str, help="Specific knowledge base ID to recover"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    recover_dedup_records(kb_id=args.kb_id, dry_run=args.dry_run)
