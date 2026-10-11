"""Opt-in, read-only PostgreSQL V6 dataset counts. No startup integration."""
import json
import os
import sys

DATASETS = (
    ("ai_ogrenme_gecmisi", "runtime/ai_ogrenme_gecmisi.json"),
    ("tahmin_gecmisi", "runtime/tahmin_gecmisi.json"),
    ("gun_ici_sonuclar", "runtime/gun_ici_sonuclar.json"),
    ("yarin_top10_sonuclar", "runtime/yarin_top10_sonuclar.json"),
    ("haber_dedup", "runtime/haber_dedup.json"),
    ("ana_motor_durum", "runtime/ana_motor_durum.json"),
)

def main():
    if os.environ.get("BIST_V6_READONLY_STATS_ONCE") != "1":
        print("[STORAGE_V6_STATS] status=DISABLED")
        return 0
    connection = None
    try:
        from v6_storage.config import Settings
        from psycopg import connect
        settings = Settings.from_env()
        settings.require_database()
        connection = connect(settings.connection_dsn(), connect_timeout=settings.timeout)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT to_regclass('bist_v6.records'), to_regclass('bist_v6.import_sources')")
                tables = cursor.fetchone()
                if not all(tables):
                    print("[STORAGE_V6_STATS] status=SCHEMA_UNAVAILABLE")
                    return 2
                for label, dataset in DATASETS:
                    cursor.execute("SELECT COUNT(*) FROM bist_v6.records WHERE dataset LIKE %s", (dataset + "#%",))
                    count = cursor.fetchone()[0]
                    cursor.execute(
                        "SELECT COUNT(*) FILTER (WHERE status IN ('VERIFIED','POSTGRES_NATIVE')), COUNT(*) FROM bist_v6.import_sources WHERE dataset=%s",
                        (dataset,),
                    )
                    verified, sources = cursor.fetchone()
                    print("[STORAGE_V6_STATS] " + json.dumps(
                        {"dataset": label, "rows": count, "verified_sources": verified, "sources": sources},
                        separators=(",", ":"), sort_keys=True,
                    ))
        return 0
    except Exception:
        print("[STORAGE_V6_STATS] status=ERROR")
        return 2
    finally:
        if connection is not None:
            connection.close()

if __name__ == "__main__":
    sys.exit(main())
