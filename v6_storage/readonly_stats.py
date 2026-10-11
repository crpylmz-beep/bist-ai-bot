"""Explicit, opt-in, read-only PostgreSQL V6 statistics CLI.

Run manually with BIST_V6_READONLY_STATS_ONCE=1. Not wired into startup.
One invocation produces one snapshot; this is NOT a durable once-only latch.
"""
import json
import os
import sys
import threading

_run_lock = threading.Lock()
_already_run = False

DATASETS = (
    ("ai_ogrenme_gecmisi", "runtime/ai_ogrenme_gecmisi.json"),
    ("tahmin_gecmisi", "runtime/tahmin_gecmisi.json"),
    ("gun_ici_sonuclar", "runtime/gun_ici_sonuclar.json"),
    ("yarin_top10_sonuclar", "runtime/yarin_top10_sonuclar.json"),
    ("haber_dedup", "runtime/haber_dedup.json"),
    ("ana_motor_durum", "runtime/ana_motor_durum.json"),
)


def main():
    global _already_run
    if os.environ.get("BIST_V6_READONLY_STATS_ONCE") != "1":
        print("[STORAGE_V6_STATS] status=DISABLED")
        return 0

    with _run_lock:
        if _already_run:
            return 0
        _already_run = True
    connection = None
    results = []
    try:
        from psycopg import connect
        from v6_storage.config import Settings

        settings = Settings.from_env()
        settings.require_database()
        # Dedicated diagnostic connection; do not alter application DSN or pool.
        connection = connect(
            settings.connection_dsn(),
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000",
            autocommit=True,
        )
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT to_regclass('bist_v6.records'), to_regclass('bist_v6.import_sources'), to_regclass('bist_v6.documents')")
                if not all(cursor.fetchone()):
                    print("[STORAGE_V6_STATS] status=ERROR reason=SCHEMA_UNAVAILABLE")
                    return 2
                for label, dataset in DATASETS:
                    # Collection rows are stored as dataset#field, never matched via SQL LIKE.
                    cursor.execute(
                        "SELECT COUNT(*) FROM bist_v6.records WHERE split_part(dataset, '#', 1) = %s AND dataset <> %s",
                        (dataset, dataset),
                    )
                    rows = cursor.fetchone()[0]
                    cursor.execute(
                        "SELECT COUNT(*) FILTER (WHERE status IN ('VERIFIED','POSTGRES_NATIVE')), COUNT(*) FROM bist_v6.import_sources WHERE dataset = %s",
                        (dataset,),
                    )
                    verified, sources = cursor.fetchone()
                    cursor.execute("SELECT COUNT(*) FROM bist_v6.documents WHERE dataset = %s", (dataset,))
                    documents = cursor.fetchone()[0]
                    results.append("[STORAGE_V6_STATS] " + json.dumps(
                        {"dataset": label, "rows": rows, "verified_sources": verified,
                         "sources": sources, "documents": documents},
                        separators=(",", ":"), sort_keys=True,
                    ))
        for result in results:
            print(result)
        print("[STORAGE_V6_STATS] status=SUCCESS")
        return 0
    except Exception:
        # Deliberately do not print exception details or credentials.
        print("[STORAGE_V6_STATS] status=ERROR")
        return 2
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                # Never expose connection details in diagnostics.
                pass


if __name__ == "__main__":
    sys.exit(main())
