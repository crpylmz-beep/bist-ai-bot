# Storage recovery V5 — isolated validation

Scope: continue commit `1f7299b377469b8c9483aad1ee6113ddedce47ee`.
No Railway connection, production file access, volume operation or production
cleanup was performed. Historical capacity/free-space figures are not current
measurements. New recovery-based deletion is **off by default**.

## Recovery and safety

`storage_schemas.py` explicitly supports AI learning history, prediction history,
intraday outcomes, canonical news (`haberler`/`canonical_id`) and tomorrow outcomes
(`sonuclar` mapping, key must equal `kayit_id`). Streaming records have an 8 MiB
entry limit; root fields and duplicate identities are validated. Unsupported
schemas stay UNKNOWN. News lifecycle/effects are never normalized away.

`storage_recovery.py` compares each record as IDENTICAL, TEMP_ONLY,
FINAL_NEWER_SAFE, TEMP_NEWER_SAFE, CONFLICT or UNRESOLVED, and counts FINAL_ONLY.
Only missing records or monotonic completed-outcome additions with identical
immutable fields can be staged. Differing frozen fields or completed outcomes
never overwrite canonical data; source and any existing journal stay intact.
Unknown/future root metadata, duplicate IDs and an unresolved/truncated tail
prevent deletion. Complete records before a truncated tail may be recovered;
the unfinished record is never fabricated.

`recovery_journal.py` reuses the V4 WAL transaction implementation but has a
separate private `.storage-recovery-v5-<dataset-hash>.wal` in runtime. It stores
actual records, not just hashes: sequence + checksum, append-only, exclusive
flock, file fsync and directory fsync. Limit: 32 MiB per dataset, 8 MiB per
transaction. Capacity/I/O failure defers recovery and retains the source.
Ambiguous prior fsync failures require fresh fsync before duplicate acknowledgement.
No automatic recovery-journal compaction/full-history rewrite is performed.

Final + journal overlay is read through the existing AI/performance load helper,
four legacy AI readers, and canonical news ingestion. Guarded normal JSON writes
also preserve overlaid recovery rows. Existing consumers already materialize
canonical JSON; the recovery/proof engine itself never materializes the full
history or writes a second full copy. Replay is idempotent, checksummed and
conflict preserving. V4 pending history WAL can coexist and merge normally.

`PROVEN_RECOVERED_REDUNDANT` is separate from the three existing proven cleanup
classes. Actual recovery-based unlink additionally requires explicit
`STORAGE_RECOVERY_DELETE_ENABLED=true`, fresh verified WAL replay, unchanged WAL
fingerprint held under journal lock, rechecked source/final fingerprints,
exclusive leases and worker/target locks. Default false retains the original
source even after successful recovery. UNKNOWN/unique/conflict/unresolved files
are not deleted. Existing proven-redundant cleanup retains its safeguards.

## SQLite root-cause evidence and fallback

The old `OperationalError errno=None` line omitted SQLite's own error code;
it alone cannot prove which failure occurred in production. Code inspection
found a real local cause: per-index `max_page_count=16384` (64 MiB at 4 KiB pages),
with shared final-record and per-orphan `seen` tables. Multiple incomplete scans
can exhaust this **index cap even when the volume has free space**. Real SQLite
fault tests reproduce SQLITE_FULL (13, errno None) and SQLITE_BUSY (5) separately.
We do not claim a production-specific exception code without production logs.

Initialization failures now close the connection; SQLite failures preserve their
code rather than being converted to an ownership/schema error. Completed recovery
scans promptly remove their reproducible `seen` entries. The bounded 64 MiB/index
and 256 MiB aggregate limits remain. Diagnostics include safe error code, SQLite
code, errno and stage, never SQL text/private payload.

If SQLite cannot be used, the fallback keeps hashed IDs and byte offsets only:
one final index and at most two source-ID sets, each bounded to 180,000 entries.
No complete JSON payload is cached. Insufficient workspace/capacity is reported
as PROOF_DEFERRED_LOW_WORKSPACE; locks, corruption, descriptors and journal errors
have distinct safe codes. Partial SQLite failure rolls back and restarts through
the bounded fallback. A worker-process restart can safely rebuild a RAM fallback
index; the normal SQLite path resumes persisted byte/record checkpoints.

V4's checksummed checkpoint remains <=256 KiB. Source/final inode, size or mtime
change invalidates progress. Committed index rows ahead of a checkpoint are
reconciled. Budget expiry is resumable progress, **not** an OSError/unresolved
record (TimeoutError is an OSError subclass; the new explicit branch fixes this).

## Preserved behavior

DISK_SPACE_GUARD, CRITICAL_STORAGE_MODE, writer lock, shutdown cleanup,
unchanged-write skip, coalescing, bounded V4 WAL, lifecycle/write/growth/leak
traces, sidecars and target fingerprints remain. The read-only Actions workflow
is unchanged and still produces a short-lived artifact instead of committing
runtime data to main. No investment/scoring/signal formula was changed.
15 protected calculation/provider/bootstrap modules are byte-identical to V4;
three modified business modules differ only in explicitly verified read plumbing.

## Validation

- 68 V5 unit/integration tests: recovery, immutable/completed conflicts, real
  SQLite FULL/BUSY, RAM fallback, private permissions, WAL capacity/corruption/
  sequence/fsync (including successful resume after transient fsync failure), duplicate replay, safe deletion opt-in, leases/recent sources,
  adapter schemas, truncated JSON, source invalidation and resume across fresh
  sessions/RAM loss; all pass.
- Storage suite: 305 tests, zero skips; all pass.
- Full Python regression: 1,689 tests, zero skips; all pass (229.185 seconds).
- 18 frontend smoke groups: all pass.
- Bootstrap: 8 tests, all pass.
- Syntax: 166 Python files, 19 external JS/CJS files and one nonempty inline
  script. Imports: 17 modules. Offline --check and real main with mocked providers,
  real scheduler/worker lock and maintenance start/join: pass.

The stress script generates its own actual large files in an owned temporary
volume; no large fixture is committed. It respects normal per-file proof budgets
and resumes both initial analysis and replay verification across maintenance
rounds. Critical free space is mocked, files and fsync are real. Large temp counts
exclude the intentionally pre-existing input orphan and small checkpoint/manifest
writes; these are reported separately.

Actual final stress measurement (all assertions passed):

```json
{
  "final_bytes": 293888967,
  "orphan_bytes": 283623060,
  "final_mib": 280.27,
  "orphan_mib": 270.48,
  "final_records": 100000,
  "orphan_records": 96507,
  "recovered_records": 7,
  "journal_bytes": 22449,
  "full_json_rewrites": 0,
  "new_large_temp_files": 0,
  "new_large_temp_bytes": 0,
  "max_new_metadata_temp_files": 1,
  "max_new_metadata_temp_bytes": 3532,
  "max_total_temp_files": 2,
  "max_total_temp_bytes": 283626592,
  "max_existing_orphan_files": 1,
  "max_existing_orphan_bytes": 283623060,
  "source_retained": true,
  "duplicate_journal_growth_bytes": 0,
  "rounds": 2,
  "replay_rounds": 1,
  "seconds": 67.84
}
```

7 real missing payloads were recovered; canonical SHA remained unchanged and the
source orphan remained intact. Repeated replay added zero bytes/duplicates.
No history rewrite or new large temp was created. Peak totals include the
original 270.48 MiB orphan plus one 3,532-byte metadata temp. The 1 GiB target was
intentionally unmet under mocked critical free space; this warning is not
suppressed and no physical production-space improvement is claimed.
