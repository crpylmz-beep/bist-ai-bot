# Atomic storage safety and DISK_FULL diagnosis

## Evidence and limits

The supplied production inventory shows approximately 3,942 MiB in runtime versus
44 MiB public and 4 MiB archives. Thirteen `.user-*` scratch files total roughly
2,869 MB in the rounded list; the protected AI history itself is about 272 MB.
The producer of `.user-*` is `kullanici_kayitlari.atomic_json`, used by runtime,
public and private user transactions. AI-history updates rewrite the complete
history, so a scratch file can be as large as the committed history.

The previous writer ALREADY used `finally` cleanup. A successful `os.replace`
consumes the scratch path; normal write/serialization/fsync/replace exceptions
execute cleanup. It is incorrect to attribute this incident to a missing finally.
A real SIGKILL test reproduces a surviving full scratch copy: hard process death
bypasses Python finally. `cloud_baslat.stop_children` can kill a child after its
25-second termination deadline; OOM kills and external hard restarts can have the
same effect. The production inventory does not establish which of these occurred,
or whether a particular scratch file was still open. The existing GitHub workflow
commits generated data every 30 minutes during its schedule; deployments configured
to follow those commits may repeatedly interrupt long-running writers. The workflow
is unchanged. A 30-minute minimum scratch age, plus active-writer and content-proof
checks, avoids requiring a full day of duplicate history space before reclamation.
Production cleanup therefore
requires evidence, never just a filename or age. This patch does not claim to have
measured or freed space in production.

## Writer inventory

| Writer / caller | Destination and scratch | Lifecycle |
| --- | --- | --- |
| `kullanici_kayitlari.atomic_json` | Caller-selected public/runtime/private final; `.user-v2-<destination hash>-*.tmp` | Central writer, per-target lock, exact size guard, fd lease, fsync, replace, finally unlink |
| `bist_bot.json_atomik_yaz` | Public TOP10 / immutable dated archives; `.snapshot-*.tmp` | Same central writer, `default=str`, atomic create-only link retained |
| `bist_bot.tahmin_gecmisi_yaz` and modern engine writers | Delegate to the above writers; final history/state/outbox unchanged | Existing caller read/modify/write locks retained |
| `veri_yollari.copy_new` | Initial migration target; `.migration-<target>-*` | Existing directory copy lock, capacity guard, create-only link, fsync and finally; unchanged |
| Historical `bist_bot_*yedek*` / backup source files | Old fixed `.tmp` implementations | Not launched or imported by production worker; no changes |
| `kap_canli_ai_bagla.py` and other patch-generation utilities | Source-edit snippets including fixed `.json.tmp` | Offline maintenance code, not the active `kap_canli` worker path |
| Existing direct `json.dump` summary/config writers | Derived summaries/config, no `.user-*` allocation | Not the orphan producer; no scoring or learning formula edits |

No append-only ledger or database migration is attempted here. The canonical
history may still grow with genuine new records; this patch does not remove them.
A changed large JSON needs one full additional copy for an atomic replacement.

## New write protocol

`atomik_depolama.atomic_write_json` serializes sizing tokens without constructing
another full JSON string, calculates exact UTF-8 length/hash, then checks free
space for the complete additional copy plus a bounded reserve. Byte-identical
large payloads are not rewritten. Changed data retains existing indentation,
Unicode, NaN rejection and snapshot serialization behavior. Writes buffer small
encoder tokens and stream to disk. Same-target process/thread commits serialize;
different destinations do not share a global lock. Existing business transaction
locks still protect read/modify/write operations.

A free-space check cannot reserve filesystem blocks against unrelated concurrent
writers. Actual ENOSPC remains an error and executes cleanup; it is not converted
to OK. Before rename, the existing final is preserved on failure. If directory
fsync fails AFTER rename, the new valid final remains and the caller receives an
error; reverting or deleting it would be unsafe. Hard kills can inherently leave
scratch files, which the next startup assesses using the proof rules below.

## Startup proof and boundaries

The worker acquires its exclusive worker lock before inspecting scratch, before
starting task executors. Each worker startup runs the idempotent inspection,
independently of the earlier one-shot reclaim marker. There is no background
recursive deletion task. Only top-level `runtime/.user-*.tmp` candidates at least
30 minutes old are considered; private user data, public data, archives and nested
folders are not traversed. Symlinks and hard-linked scratch candidates are refused.
Root/runtime directory descriptors anchor all operations. Active fd leases, busy
final transaction locks, or an uncertain same-user `/proc` open-file audit block
deletion. Protected final names are an explicit allowlist.

A candidate is eligible only when one of these proves it adds no unique data:

* Its complete bytes equal a protected current final.
* Its complete bytes are an exact prefix of a longer protected final (including
  interrupted JSON writes whose bytes already exist in the current final).
* It is a fully parsed AI history whose frozen records and every non-null outcome
  exist unchanged in the current AI history. Duplicate IDs/keys, changed scores,
  changed results, unmatched metadata, missing finals and incomplete unmatched
  histories are retained. A newer completed result can supersede an old null
  result; an old non-null result must match exactly.

Final and candidate inode/size/mtime are checked again before unlink. History
comparison parses one bounded record at a time and uses a temporary SQLite hash
index under `/tmp`, never `/data`, which is closed and removed after inspection.
Inspection has a time budget; unverified files survive budget exhaustion. No
unique recovery copy or canonical history is deleted. This conservatism means
that not all listed scratch bytes are guaranteed reclaimable.

## Operational logs

`[DISK_TEMP_INVENTORY]` adds scratch count, total bytes, newest/oldest age to the
existing disk report. `[DISK_TEMP_CLEANUP]` reports scanned, eligible, removed,
freed_bytes, skipped_recent, skipped_unverified, skipped_active, errors, and actual
before/after free bytes. Removed logical bytes are distinct from actual free-space
change. `[DISK_SPACE_GUARD]` reports required/reserve/free sizes only. Logs expose
no record contents, private filenames, subscription keys or tokens.

Production checks belong to the operator after deployment: confirm inventory and
cleanup counters, actual free space and task status. No Railway/volume operations
are part of this patch, and no guarantee of production freed bytes is made.

## V2 forensic recovery

The old aggregate `skipped_unverified` counter did not identify whether a decision
came from process auditing, a time limit, unsupported structure or a real mismatch.
The repository exposes three concrete proof blockers: `ai_ogrenme_kaydet` writes
naive Istanbul root clocks; `ai_sonuclari_guncelle` advances a flat legacy result
bundle and `egitim_durumu`; and `PerformansMotoru.enrich` adds fields to existing
records. Strict whole-record hashes and aware-only timestamps rejected safe
supersets in those cases. Actual production files have not been read by this patch,
so the individual reasons for all 104 files cannot be asserted in advance. The
existing 100,000-record producer limit can also make an older scratch copy contain
records absent from the current final: these are recovery candidates, never trash.
No producer, limit, score or raw-history write is changed by this recovery patch.

`disk_forensik.inspect_atomic_temps(cleanup=False)` is a read-only classifier for
the persistent volume: it creates no volume locks or manifests and unlinks nothing.
Small JSON is bounded to 8 MiB; huge histories use record-at-a-time parsing. A
transient index in `/tmp` stores only stable IDs, hashes and byte offsets. On a hash
mismatch, the corresponding final record is read by offset to verify that EVERY
old frozen field is contained unchanged, allowing additional enrichment fields.
The index does not store or copy whole history payloads. UTF-8/CRLF offsets are
accounted for, and complete parsing rejects duplicate IDs/keys and malformed JSON.

Six classifications are emitted:

* PROVEN_REDUNDANT: size/SHA-256 equality, or every scratch byte already exists as
  a complete prefix/suffix of a protected final. This can also prove a truncated
  scratch contains no unique recovery bytes.
* PROVEN_SUBSET_OF_FINAL: every old stable record, frozen value and non-null result
  is contained; a growing AI history has additional current records. Generic
  structural comparison is permitted only for a routed v2 destination; an
  unrelated legacy JSON shape is not sufficient to identify its dataset.
* PROVEN_OLDER_COMPLETE_COPY: the full AI record set is retained, root housekeeping
  clocks/counts are valid, and outcomes are identical or documented pending values
  have completed. Completed results must match exactly. Only the explicit legacy
  GUN_ICI pending defaults can advance; observed partial or changed results survive.
* ACTIVE_OR_RECENT: younger than 30 minutes, an active fd lease, or another process
  has the scratch open.
* UNIQUE_RECOVERY_CANDIDATE: fully parsed identified data has a missing/changed
  record, frozen field, non-null outcome or non-housekeeping metadata value.
* UNKNOWN: uncertain process audit, missing destination, unrecognized schema,
  malformed unmatched data, locks/races, unsafe paths or exhausted budget.

Only the three PROVEN classes can be unlinked. Age or extension alone never
qualifies. An exact duplicate/prefix/suffix proves byte containment independently
of JSON validity; other invalid/truncated files remain UNKNOWN. Legacy names do
not encode a destination. New v2 destination hashes are routing hints, never sole
proof. Unknown root clocks are not assumed to be expendable housekeeping.

Cleanup is permitted only inside the actual exclusive worker-lock context. The
same destination business/I/O locks and scratch leases remain held across proof
and unlink, and inode/size/mtime are checked again. Inventory runs first; candidates
are processed largest first, within a 180-second startup budget. Free space is
measured after every successful removal, after closing the unlinked scratch
descriptor so its blocks are released. The target is at least 1 GiB; all proven
files can continue to be reclaimed within the budget. A target shortfall does not
relax proof or remove unique/unknown files. The existing write-space guard remains
unchanged and receives actual restored filesystem free space.

`[DISK_FORENSIC]` provides six class counts, eligible bytes and safe reason codes,
including PROCESS_AUDIT_UNCERTAIN and BUDGET_EXHAUSTED. `[DISK_TEMP_CLEANUP]` splits
unique/unknown skips and records actual before/after free space. No payload, record
ID or private filename is logged. `runtime/disk_cleanup_manifest.json` is a bounded
last-run manifest with timestamp, class, size, hash prefix, reason and whitelisted
logical dataset; at most 256 entries, total removed count/bytes, no content backups.
If its write fails, the failure is logged and existing canonical data remains safe.

The supplied 4,064,671,496 scratch bytes are a theoretical upper bound, NOT measured
proven reclaimable bytes. Actual eligibility can be zero if old copies contain
pruned records or another safety check is inconclusive. Production verification is
left to the operator; no Railway/volume/manual production actions were performed.
