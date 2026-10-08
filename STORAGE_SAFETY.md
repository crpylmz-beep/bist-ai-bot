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
