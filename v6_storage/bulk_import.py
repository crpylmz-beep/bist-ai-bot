"""One-shot, non-destructive import of all currently supported V6 JSON sources.

Run at runtime with /data mounted: python -B -m v6_storage.bulk_import --apply
Never changes STORAGE_BACKEND or removes source files.
"""
import argparse
import json
from pathlib import Path
from veri_yollari import paths
from .config import Settings, StorageError
from .migration import Migrator
from .records import shape_for


def sources(location):
    candidates = list(location.runtime.glob("*.json"))
    for directory in ("gunluk_al_sat_gecmisi", "intraday_signal_results"):
        candidates.extend((location.runtime / directory).glob("*.json"))
    candidates.extend(location.archives.glob("*.json"))
    for path in sorted(set(candidates)):
        if path.is_file() and not path.is_symlink() and shape_for(path, location) is not None:
            yield path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args(argv)
    location = paths()
    if not location.root or location.root != Path("/data"):
        print(json.dumps({"status": "BLOCKED", "reason": "EXPECTED_DATA_VOLUME_NOT_MOUNTED"}))
        return 2
    database = None
    completed = 0
    unresolved = 0
    try:
        from .postgres import PostgresStore
        database = PostgresStore(Settings.from_env())
        database.ready()
        for source in sources(location):
            # A malformed or changing source must not prevent later files
            # from being processed. Never expose source content in logs.
            try:
                result = Migrator(database).run(source, shape_for(source, location), apply=True)
            except Exception as exc:
                result = {"status": "UNRESOLVED", "records": 0,
                          "error": "UNEXPECTED_" + type(exc).__name__}
            completed += result["status"] == "VERIFIED"
            unresolved += result["status"] != "VERIFIED"
            print(json.dumps({"source": str(source.relative_to(location.root)),
                              "status": result["status"],
                              "records": result.get("records", 0),
                              "error": result.get("error")}), flush=True)
    except (StorageError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": getattr(exc, "storage_code", type(exc).__name__)}))
        return 2
    finally:
        if database is not None:
            database.close()
    print(json.dumps({"status": "DONE" if unresolved == 0 else "PARTIAL",
                      "verified_sources": completed, "unresolved_sources": unresolved,
                      "source_deleted": False, "backend_switched": False}), flush=True)
    return 0 if unresolved == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
