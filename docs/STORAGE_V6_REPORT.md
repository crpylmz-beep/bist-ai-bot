# V6 implementation / validation report

## Scope and verified boundaries

V6 opt-in storage infrastructure is implemented. Production `/data` was not accessed, inspected, migrated, cleaned or deleted. No Railway operation, volume operation, database provisioning, R2 bucket creation or paid resource creation occurred. The user's 5 GB / 4.43 GB figures are not our disk measurements. Production disk relief is NOT claimed.

Defaults remain `STORAGE_BACKEND=legacy`, `STORAGE_POSTGRES_CUTOVER_ACK=false`. No schema migration, PG connection, R2 transfer or cutover runs automatically on imports/worker start. Existing V5 sources/journals and the default legacy protections remain. Shadow/postgres maintenance is read-only and does not flush a legacy WAL back into a large JSON.

## Analysis

84 distinct JSON literal names and 20 tracked JSON files were inventoried from repository code/assets. Full references are in `STORAGE_V6_INVENTORY.json`; cloud path classifications and writer analysis are in `STORAGE_V6.md`.

Large atomic JSON commits require old + new complete files until rename, with possible orphan candidates after interruption. Growing immutable histories also legitimately retain unique information. V4 reduces repeated writes and guards headroom; V5 conservatively retains unresolved conflicts, missing provenance, malformed/truncated streams and unproved lifecycle changes. These are code-derived causes; production directory byte attribution was not verified.

## Implemented

- Four checksum-versioned explicit SQL migrations; pooled/batched PG operations and safe type/SQLSTATE errors.
- Dataset + stable original IDs, immutable forecast and completed outcome triggers; no new future forecast fields attached retroactively.
- Separate mutable lifecycle, 1/3/5/10/20/60 outcome records, symbols/source/quality/job/error/usage/archive proof tables.
- Ordered current projections preserve existing producer windows; historical rows remain stored. Dataset revisions invalidate indicator caches when old JSON mtime is unchanged. No scoring formula or learning-window expansion is introduced.
- Legacy/shadow/postgres routing. Shadow compares the durable legacy document (including V5 overlay), not merely an uncommitted input object. PG mode requires explicit acknowledgement + verified import; newly dated signal datasets are distinctly labeled POSTGRES_NATIVE and use small discovery sentinels.
- Bounded fsynced private pending WAL, duplicate pending-intent protection, original row IDs, atomic DB replay receipts and compare-and-swap projection deltas. WAL/conflict sources remain retained. Unverifiable reordering or insufficient WAL capacity produces an explicit failure, never a false acknowledgement.
- Default DRY_RUN streaming import, source fingerprints/raw SHA-256, original/mapping identities, duplicate/malformed/missing source handling, same-transaction receipts/checkpoints, resumable record positions, explicit unresolved conflicts; no source deletion.
- V5 recovery-journal reader does not create source locks in dry-run; conservative import preserves conflicting source and DB records. Unrecognized temp schemas require byte-preserving archival/operator review; they are not blindly imported.
- Private R2 gzip multipart transfer with bounded buffers, retries, full read-back raw/compressed SHA-256, content-addressed/versioned objects and dated manifests. Completion-before-manifest interruption can be repaired by proving existing bytes without re-upload. Restore creates only a new target, guarded by headroom; it removes only its newly allocated failed scratch.
- Read-only disk measurement, PG database-size and bounded/coverage-marked R2 inventory APIs, 32-day usage metadata and daily growth warnings. No trading-history retention/deletion command or automatic cloud archiver was added.

## Regression evidence

- Full Python regression: **1,742 tests**, all pass, **zero skips**. Baseline 1,689 plus 53 V6 unit tests.
- Additional real LOCAL PostgreSQL integration: **28 tests**, all pass, no skips. Each run uses a newly created DB in our owned RAM-backed PostgreSQL 17 container, not production.
- Total distinct Python test cases: **1,770**; **81 new V6 cases** (53 + 28).
- Frontend: **18 smoke groups**, all pass; no frontend files changed.
- Syntax: **179 Python files**, **19 external JS/CJS files**, **1 nonempty inline JS script**; pass. Imports: **24 modules**, pass.
- Offline worker: `--check` plus real `main()`/scheduler/flock/maintenance start+join/shutdown/STOPPED heartbeat with mocked providers; pass.
- 15 protected calculation/provider/bootstrap modules are byte-identical to the V5 base. All 52 non-I/O top-level functions in `bist_bot.py` have identical ASTs. Five modified BIST functions change only history read plumbing / propagation of typed storage failures. Indicator performance changes only storage freshness signature. Existing worker schedule/task gates and formulas remain.
- Intraday feature default remains true; TOP10 learning ±3, BASE/LEARNED, prediction formulas, Tomorrow Plan, market/sector formulas, XIST/XUTUM/provider behavior, company-site isolation, alarm and push remain unchanged.

New coverage includes repeat migration, incomplete/broken/duplicate/missing JSON, original IDs, all positive candidates, missing mapping IDs without invented payload fields, immutable SQL UPDATE/DELETE protection, completed horizons, retained omitted historical records with unchanged active learning window, interrupted/resumed migration, real PG failures without secret messages, retry/WAL replay/idempotence/CAS projections, conflicting recovery records, midnight new-day native signals, rollback certification, low-space restore, R2 503/checksum failures, manifest repair, source/temp preservation, SDK protocol stubbing and no legacy WAL rewrite in PG maintenance mode.

## Actual isolated large-file test

`tests/storage_v6_stress.py`, local fixture only:

- Source: **293,660,916 bytes / 280.06 MiB**, 1,000 records.
- 100 completed outcome updates.
- Source SHA-256 unchanged.
- Full JSON rewrites: **0**.
- New local temp peak: **0 files / 0 bytes**.
- PG DB size before updates: **13,792,947 bytes**; after: **13,858,483 bytes**; delta **65,536 bytes / 64 KiB**.

This is a repetitive synthetic fixture exercising the row store/importer, not a production compression estimate or full-application latency test. `pg_database_size` does not measure shared PostgreSQL WAL, provider backups or billable compute. No such production growth/cost claim is made.

## Cost and remaining operator gates

Official Railway/Neon/Supabase/R2 pricing pages returned ProxyError here. Current prices and the extra $10/month target are unverified. Separate 5/10/25/50/100 GB hot-PG and compressed-R2 formulas/scenarios are in `STORAGE_V6_COSTS.md`. No remembered price is presented as a current quote, and no paid resource was created.

Before production cutover: verify official current cost/limits and obtain provisioning authorization; establish funded staging PG/private R2 credentials; run explicit schema + source inventory/dry-run/import/verification; archive unresolved unique bytes without deletion; compare shadow results and current projections; authorize cutover separately; then observe production disk/API/task behavior. Legacy rollback requires a current verified export/adoption/certification, not reuse of stale JSON.

Existing close gate is **18:15**, not 18:05. This storage task deliberately does not change that schedule or claim it already meets 18:05. Public JSON, user files, dated archives, learned-model state and other unsupported live schemas stay retained in legacy locations; support tables/R2 do not imply they have already been migrated.

The cloud onboarding install/start instructions and environment variable requirements were saved as a **draft**, with no secret values. Saving is not applying/publishing. Review/save/publish through environment settings is required to activate that reusable setup; fresh-task restoration was not tested.

Git commit/push/remote SHA verification is reported in the final response after actual publication. This report contains no prospective commit hash or fabricated production verification.
