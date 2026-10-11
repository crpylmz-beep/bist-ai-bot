"""Read-only PostgreSQL cutover diagnostics. Never modifies records."""
import json
from collections import Counter
from v6_storage.config import Settings
from v6_storage.postgres import PostgresStore

def main():
    db = PostgresStore(Settings.from_env())
    try:
        with db.transaction() as conn:
            conn.execute("SET TRANSACTION READ ONLY")
            unresolved = list(conn.execute("""
                SELECT source_id, dataset, status, cursor, updated_at
                FROM bist_v6.import_sources
                WHERE status NOT IN ('VERIFIED', 'POSTGRES_NATIVE')
                ORDER BY updated_at DESC
            """))
            conflicts = list(conn.execute("""
                SELECT dataset, record_id, reason
                FROM bist_v6.conflicts
                ORDER BY dataset, record_id
            """))
        print(json.dumps({
            "unresolved_sources": [
                {"source_id": r["source_id"], "dataset": r["dataset"],
                 "status": r["status"], "updated_at": str(r["updated_at"])}
                for r in unresolved
            ],
            "conflicts_total": len(conflicts),
            "resolution_policy": "PRESERVE_BOTH_NO_AUTOMATIC_OVERWRITE",
            "conflicts_by_dataset": dict(Counter(r["dataset"] for r in conflicts)),
            "conflicts": [
                {"dataset": r["dataset"], "record_id": r["record_id"],
                 "reason": r["reason"]}
                for r in conflicts
            ],
            "mutated": False
        }, ensure_ascii=False))
    finally:
        db.close()

if __name__ == "__main__":
    main()
