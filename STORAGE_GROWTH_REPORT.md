# Storage growth and V3 recovery

## Production evidence and limits

The supplied V2 production report shows 99 remaining runtime `.user-*` files,
3,424,384,156 logical bytes, and approximately 795,398,144 free bytes. This is
not proof that those 99 files are removable. Their contents are unavailable in
this development environment. V3 emits masked per-file evidence at the next
worker startup and maintenance round; it does not invent an actual reclaimed
byte count or a production classification. No Railway/SSH/manual cleanup occurs.

## Growth inventory

| Dataset | Cause / measurement | Policy and future architecture |
| --- | --- | --- |
| `runtime/ai_ogrenme_gecmisi.json` | ~270+ MB per supplied report; new frozen observations, indicator vectors and 1/3/5/10/20/60-session outcomes; a changed atomic commit needs a full additional copy | Preserve observations and completed outcomes. Existing producer's 100,000-row cap is unchanged; old scratch may contain uniquely pruned rows and must remain. Future transactional SQLite tables for observations, features and outcomes; migration requires separate validation. |
| `runtime/tahmin_gecmisi.json` | Meaningful signals appended with frozen rankings, model data and horizon results | Preserve all unique predictions and follow-up results; future keyed transactional prediction/outcome tables. |
| `runtime/sinyal_performansi.json` and public signal reports | Derived aggregations can change even with identical samples; identify actual producer/path rather than trusting the basename | Unique historical evidence and inputs remain protected. Only explicitly rebuildable summaries can have separately designed retention; V3 does not add deletion policy. |
| `runtime/indicator_performance_state.json`, public indicator reports, dated indicator archives | Source fingerprints, report hashes, indicator combinations and per-horizon aggregates; archives grow on actual changed reports | Preserve learning evidence and immutable archives; possible database for observations/features with bounded derived summaries, no migration here. |
| `runtime/intraday_signal_performance_state.json`, public intraday reports, `runtime/gunluk_al_sat_gecmisi/` | Frozen 5-minute signal events and multiple intraday/session outcomes | Unique events/outcomes must be kept; future event/outcome tables. Derived report retention requires proof of full regeneration from protected inputs. |
| `runtime/gun_ici_sonuclar.json` | Signal/list occurrences and outcomes; lifecycle fields may change | Frozen inputs/completed results protected. Lifecycle changes are NOT ignored by the generic proof adapter. |
| `runtime/gun_ici_mumlar.json` | Historical OHLC observations accumulate with symbols and sessions | Needed to replay performance and avoid lookahead; never treat as disposable provider cache. Future bar table keyed by symbol/time, retention only after downstream replay requirements are documented. |
| `runtime/performans_fiyat_cache.json` | Re-fetchable daily provider replay cache | Existing 3-day / 4-MiB bounding remains; not equivalent to unique intraday bars. |
| `runtime/.user-*` | Interrupted complete rewrites, partial writes, concurrent shutdown/hard kill | Not history growth. Only three proven classes removable, minimum 30 minutes, worker/target locks, temp lease, process audit, unchanged inode/size/mtime and content proof required. |

To measure daily growth, compare `stat` byte sizes and record counts for the SAME
named dataset at comparable Istanbul session times. Capture `[DISK_HEALTH]`
(capacity, used, free, percentage, temp count/bytes) and inventory logs externally
for 7+ days. Separate final-file growth from scratch growth and freed bytes.
Report delta/day and time-to-watermark from measured deltas; do not estimate a
numeric daily rate from one sample. No unbounded on-volume measurement log is added.

## Recovery protocol

Largest-first startup proof remains bounded to 180 seconds. A low-priority worker
thread continues every 300 seconds with 60-second rounds. It inherits the actual
worker-lock context and is joined before that lock is released. Per-target lock
contention is nonblocking. During background indexing only, target locks are
released after descriptors are captured, and reacquired before any deletion.
The writer can replace the final without waiting for the long index pass; an
inode/size/mtime change then invalidates the proof and preserves the temp. The
temp lease stays held throughout. Startup V2 locking remains unchanged. In-memory masked cursors rotate past exhausted/locked
candidates, reset after a complete sweep and are never used as deletion proof.
Shutdown cancellation is checked between parse/read chunks. No full extra history
copy is produced; SQLite identity/hash/offset indexes live in `/tmp`, and final
records are read individually from held descriptors. An individual JSON entry
above 8 MiB remains unsupported; budget exhaustion remains UNKNOWN. A long proof
that cannot finish in a round remains preserved, not falsely marked redundant.

Legacy AI flat-result defaults and naive Istanbul housekeeping timestamps retain
V2 rules. Prediction history's `tahminler` adapter recognizes string stable IDs,
null `sonuc_Ng` placeholders and its writer's `son_guncelleme` clock. Only added
frozen/outcome fields are tolerated. Changed existing fields, completed results,
root metadata and missing records prevent deletion. Gün İçi `kayitlar` with the
verified id/symbol/signal-time/entry-price/outcomes shape also uses the streaming
index; all lifecycle fields remain strict. Legacy indicator/signal report versions
can be identified for bounded structural comparison, with source/report-hash
changes preserved. Arbitrary PENDING dictionaries
are NOT normalized. Lifecycle transitions such as `takip.status`, `degerlendirme`
or source fingerprints remain meaningful unless separately proven; UNKNOWN and
UNIQUE_RECOVERY_CANDIDATE are never discarded to reach a disk target.

Every file has a masked identifier, size, age where safely inspectable, target/schema,
proof method and reason. Record counters are null when no record comparison was
performed, not fabricated zeros. Logs include class counts/bytes and actual free
space. The deletion manifest retains at most 256 metadata-only entries including
per-unlink free-before/free-after. It is not a content backup or unlimited ledger.

## Prevention and write behavior

The existing central writer keeps same-target serialization, fd leases, finally
cleanup, byte-identical large-write avoidance and the exact required-size guard.
Normal failures and gracefully handled SIGTERM execute finally; SIGKILL inherently
cannot. Orphans after hard kill require the next proof round. Duplicate unchanged
large commits coalesce by exact encoded bytes/hash under the target lock. Changed
housekeeping timestamps still change bytes and are not suppressed: ignoring them
could change freshness semantics. No asynchronous write batching is introduced;
acknowledged persistent writes must not be silently dropped on shutdown.

NORMAL is below 75%, WATCH at 75%, WARNING at 80%, CRITICAL at 90%. Watermarks
are observational, not permission to delete more data or drop persistent writes.
The existing DISK_SPACE_GUARD remains authoritative and raises an explicit error
before allocating a full large scratch file when sufficient headroom is absent.
Concurrent unrelated writers may still race for space; actual ENOSPC stays visible.
The 1/2-GiB goals never weaken any proof or safety boundary.
