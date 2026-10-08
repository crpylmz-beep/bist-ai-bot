# V6 storage: implementation and safe operator procedure

Default: `STORAGE_BACKEND=legacy`. No paid resource, real database, R2 bucket or production migration is created by this change. Imports and worker startup do not run schema migrations. No production volume has been inspected or modified. The reported 4.43 GB / 5 GB is the user's measurement, not a measurement by this implementation.

## Code-derived inventory and root cause

`STORAGE_V6_INVENTORY.json` enumerates JSON literals and module/line references from the repository. It is a code inventory, not a production directory listing. Dynamic daily paths and WALs are described below. Classification is conservative: unknown files are preserved. A file with `cache` in its name is NOT sufficient deletion authorization.

| Class | Cloud path / source | Treatment |
|---|---|---|
| Forecast/learning memory | `/data/runtime/ai_ogrenme_gecmisi.json`, `tahmin_gecmisi.json` | PG records, immutable forecast, separate outcomes and mutable lifecycle |
| Intraday outcomes and replay prices | `runtime/gun_ici_sonuclar.json`, `gun_ici_mumlar.json` | Outcomes routed to PG; OHLC retained unchanged, archive to R2 explicitly |
| Daily AL/SAT | `runtime/gunluk_al_sat_gecmisi/YYYY-MM-DD.json`, `intraday_signal_results/YYYY-MM-DD.json` | Events retain original mapping IDs; outcomes separated |
| Tomorrow outcomes | `runtime/yarin_top10_sonuclar.json` | PG mapping, immutable completed horizons |
| Frozen snapshots/all positive candidates | `/data/archives/yarin_top10_arsiv/YYYY-MM-DD.json`; `top10`, base/shadow lists, `pozitif_havuz.adaylar` | JSON archives kept, immutable PG mirror; no candidate limit imposed by storage |
| User data | `/data/private/user-data/...`: levels, price alarms, subscriptions, notification events | Private legacy JSON retained; not public, not silently migrated |
| News/indicator/model archives | Runtime dated histories, learned weights, original versioned decisions | Unique history preserved; explicit streamed R2 archive; unsupported schemas not claimed migrated |
| Recovery / conflicts | `.storage-recovery-v5-*.wal`, `.ai-history-pending-v4.wal`, `.user-*`, unresolved manifests/checkpoints | Never automatically removed; V5 validated recovery operations can be imported conservatively; unknown temp is R2-only until schema/provenance verified |
| Reproducible bounded cache | `performans_fiyat_cache.json`, current provider/index/sector snapshots | Existing TTL/size limits kept; no new cleanup |
| Worker/usage metadata | `/data/runtime/ana_motor_durum.json`, V6 usage samples | Small current JSON; PG job/quality/error tables available; daily usage metadata limited to 32 days (not trading history) |

Without `BIST_DATA_DIR`, `veri_yollari.py` preserves the old layout, including selected historical files under `webapp/data` and `.local/runtime`. With `/data`, public/current API files are `/data/public`, users are private, runtime is private and archives are separate.

Code-confirmed amplification: guarded atomic writers require a complete new temporary file plus the old JSON during commit. Historical producer updates may rewrite the same large AI document twice during one performance round. Interrupted writes/restarts can leave orphan candidates, and frozen archives and unique outcomes legitimately grow over time. V4 coalescing/guards and V5 recovery mitigate this, but do not make JSON append-efficient. These mechanisms explain the potential growth; the exact production byte distribution has NOT been measured here.

V5 leaves unresolved data when identities/schema are missing, metadata counts/times disagree, streams are truncated, immutable forecasts/completed outcomes conflict, lifecycle cannot be proved newer, or the forensic workspace cannot complete safely. Unresolved is a protection decision, not deletion eligibility. V6 keeps both source and conflicting incoming record.

## PostgreSQL

Environment-only configuration:

- `STORAGE_BACKEND=legacy|shadow|postgres` (default `legacy`).
- `BIST_POSTGRES_DSN` or `DATABASE_URL`; remote connections require `sslmode=require`, `verify-ca` or `verify-full`. Prefer verified certificates.
- `STORAGE_POSTGRES_CUTOVER_ACK=true` only for an operator-approved cutover.
- Optional `STORAGE_BATCH_SIZE` (100), `STORAGE_POOL_SIZE` (4), `STORAGE_TIMEOUT_SECONDS` (10), bounded in code.

No DSN/password is printed. Driver failures report type/SQLSTATE, without raw connection exceptions. Explicit migration:

```sh
python -m v6_storage schema
python -m v6_storage migrate /data/runtime/ai_ogrenme_gecmisi.json
# Only after reviewing dry-run and funding/credentials:
python -m v6_storage migrate /data/runtime/ai_ogrenme_gecmisi.json --apply --budget-records 1000
```

DRY_RUN creates no source lock, temporary copy or database connection. Streaming import verifies source fingerprints and SHA-256, retains original IDs, and commits row receipts and record-position checkpoints in the SAME DB transaction. A restarted importer skips committed positions after revalidating the full source fingerprint/hash; it still rescans the source to confirm parsing and identities. This is record-position resumability, not constant-time byte seeking. Budget exhaustion is explicit, not successful completion. Broken/unknown/conflicting sources remain UNRESOLVED and retained.

Schema version checksums prevent modified migrations being silently reapplied. Keys are dataset + original ID; source/collection receipts are unique. Immutable forecasts and completed outcomes have database triggers blocking UPDATE/DELETE. Lifecycle is separate. No omission is interpreted as deletion from the historical records table. A separate ordered current projection preserves the legacy producer’s active list/window exactly, so keeping older archived records does not silently expand scoring/learning inputs. Projection IDs are rewritten only when membership changes, not on every outcome update. New forecast fields on an existing frozen record are conflicts too; future features cannot be retroactively attached. The extension table is reserved, not used to enrich live forecast payloads. Arbitrary additional record kinds (scans, signals, algorithm/indicator performance, quality, candidates) use the same generic normalized store. `symbols`, `data_sources`, job/error/quality, daily usage and archive proof tables support dedicated metadata.

`shadow` keeps canonical legacy writes first, then mirrors and compares reconstructed content. A mismatch/failure raises and logs a real storage error; it is never reported as an OK mirror. PostgreSQL mode requires acknowledged cutover and a VERIFIED source import before routing growing histories away from JSON. Indicator source cache signatures use transactionally incremented PostgreSQL dataset revisions, so an unchanged legacy JSON mtime cannot hide new outcomes. No indicator formula changes. Small public JSON and frozen snapshot files remain for existing API/file-existence consumers. New daily signal datasets can begin natively only after explicit cutover acknowledgement; a small empty-collection sentinel retains existing file-glob discovery while actual events live in PostgreSQL. Native datasets are labeled POSTGRES_NATIVE, not falsely reported as imported legacy sources.

PostgreSQL history updates write changed rows/outcomes, not a new full JSON on disk. The application can still materialize its history in RAM; this is not a rewrite of the scoring algorithm. On connection loss after a successful read, changed rows can be retained in a bounded private `.v6-pending-*.wal` (32 MiB, 8 MiB per transaction), using V4's checksummed/fsynced writer. Failure remains explicit. Without a verified baseline, no guessed delta or stale fallback is acknowledged. Replay is explicit via `backend.replay`, with atomic DB receipts; journals are retained, never automatically compacted/deleted.

Legacy rollback after PostgreSQL writes is blocked by a small cutover marker until an operator exports and adopts verified current data. `python -m v6_storage export SOURCE NEW_TARGET` writes only a NEW target with atomic disk guards. Then verify/adopt in a separately approved operation and explicitly call `backend.certify_rollback` against matching live DB content. Do not simply set `legacy` and reuse stale pre-cutover JSON. There is no automated production rollback or source replacement.

## R2

Required only for explicit R2 operations:

- `R2_ENDPOINT_URL=https://ACCOUNT.r2.cloudflarestorage.com`
- `R2_BUCKET` (private bucket, no public access enabled)
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`
- `R2_PRIVATE_BUCKET_CONFIRMED=true` after operator verifies bucket privacy.

The S3 API does not prove Cloudflare's separate public-access setting; the confirmation is an explicit prerequisite, not a claim that code has independently audited it. Least-privilege credentials should be restricted to the chosen bucket.

```sh
python -m v6_storage archive SOURCE              # read-only preview
python -m v6_storage archive SOURCE --apply      # explicit external upload
python -m v6_storage restore MANIFEST NEW_TARGET # preview
python -m v6_storage restore MANIFEST NEW_TARGET --apply
```

Two streaming source passes compute SHA-256 and gzip bytes with bounded multipart buffers (1 MiB reads, 5 MiB minimum parts). No full compressed or raw copy is created on `/data`. Content-addressed, versioned object names prevent duplicate payload uploads; manifests contain Istanbul date/time, both sizes and checksums. Full object download/decompression verifies raw and compressed SHA-256 before VERIFIED manifest publication. The multipart ETag is NOT treated as SHA-256 proof. Bounded retries cover transient errors; failures abort only the owned upload, never source/unknown objects. Restore rejects existing/symlink targets, checks raw-size headroom, validates streamed decompression and commits one owned scratch using a hard link; only that newly allocated scratch is removed on failure.

Archive is NOT deletion authorization. R2 backups, database rows and recovery sources must all be independently verified before any future separately authorized retirement of legacy data. This release has no retirement or production cleanup command.

## Growth and autonomous behavior

`python -m v6_storage usage` is read-only. Disk report uses opaque file tokens/category, avoiding user identities. `usage.measure` supports daily disk/DB/R2 measurements, bounded 32-day metadata and a configurable growth warning (default 100 MiB/day), with partial R2 inventory explicitly marked. It is an explicit operator/tool API, NOT a newly enabled cloud task. No source history retention or cleanup is introduced. In shadow/postgres modes, existing maintenance inspections are read-only and legacy WAL full-JSON flush is deferred; all V5 sources stay preserved. Legacy V5 behavior remains unchanged.

Existing schedules, XIST/BIST calendar, timezone, provider safety, scoring, TOP10 learning ±3, BASE/LEARNED, prediction memory, intraday AL/SAT default flag and company-site isolation remain. Storage outcomes accept all 1/3/5/10/20/60 horizons without calculating or changing trading-day results. Existing worker close gate is **18:15**, not 18:05; this release does not falsely claim or silently alter that schedule. Small health/worker JSON persists through the existing code. Full candidate persistence is supported by the storage model; upstream producer limits were not changed.

This prepares safe migration, but does NOT assert the production disk is fixed while legacy remains enabled. An actual funded/verified PG + R2 connection, complete import and shadow comparison, explicit cutover and production observation are still required.

## Validation commands

```sh
python -m unittest discover -s tests
for f in tests/*.cjs; do node "$f" || exit 1; done
# Owned disposable localhost PG only (never a production DATABASE_URL):
BIST_V6_TEST_DSN=postgresql://postgres@127.0.0.1:PORT/postgres python -m unittest discover -s tests -p storage_v6_postgres_integration.py
BIST_DATA_DIR=/tmp/OWNED_TEST_DIR python ana_motor.py --check
```

The PG integration suite deliberately requires an explicit localhost test DSN. It is a separate integration runner, not a silently skipped discovered test. Real PG tests use RAM-backed disposable storage; R2 uses fake sender/fault injection. No real R2 integrity or production migration is claimed.
