# Storage V4 writer envanteri ve doğrulama

Bu inceleme kod/Git/test kanıtıdır. Railway bağlantısı, SSH veya production dosya
silme yapılmadı. Üretimdeki 102 temp / 4,013,171,168 byte ve free değişimi kullanıcının
ölçümüdür; tek tek dosyaların transaction/writer kimliği eski loglardan bulunamaz.
508,043,264 → 201,859,072 düşüşü **306,184,192 byte** ek kullanımdır. Kod, bir
AI-history full rewrite'ın bu ölçekte ek scratch ayırdığını kanıtlar; bu olayın
hangi transaction, hard kill veya başka dosyaya ait olduğu **henüz kanıtlanmadı**.
1/2 GiB boş alan hedefinin production'da sağlandığı bu çalışmada iddia edilmez.

## Kök neden ve mevcut korumalar

Tek fiziksel `.user-*` allocator: `atomik_depolama._atomic_write_json`.
`kullanici_kayitlari.atomic_json` tüm aktif ana motorların ortak wrapper'ıdır.
`bist_bot.json_atomik_yaz` aynı writer'ı `.snapshot-` prefix'iyle çağırır; bu
çağrıları `.user-*` üreticisi olarak saymak hatalıdır. `copy_new` `.migration-`
scratch kullanır. NamedTemporaryFile ile başka aktif `.user-*` üretimi yoktur.
Aşağıdaki tüm statik wrapper/caller noktaları tek tek listelenmiştir; çağrı
noktası sayısı fiziksel allocator veya production çağrı sayısı değildir.
Kaynak yedekleri/kurulum scriptleri repo içinde direct json.dump/copy2 içerir,
ancak web/worker giriş akışı onları import/execute etmez. Production için
bunlar ikinci bir aktif temp allocator veya günlük otomatik backup değildir.

`performans_motoru.one_round` shared history'yi turda iki defa yazar (eski
kaynak 521/577); varsayılan 900 saniye. İkinci çağrı sonuç değişmese de root
clock'u yeniler. `AiKararMotoru.batch` her batch sonunda yazardı (654);
priority her 2 saniyede en çok 3 başarılı sembolü ayrı AI batch'e yollar,
full_scan her 30 saniyede bir başarılı teknik batch'i AI'ya yollar (seans açık).
Gerçek frekans queue/başarı/seans/env/backoff'a bağlıdır. BIST legacy gün içi
AI append ve outcome refresh de aynı history'ye `.snapshot-` ile full rewrite
çağırır; intraday task varsayılan 300 saniyedir.

Önceki writer zaten target flock + temp fd lease + finally cleanup kullanıyordu.
Aynı final için threads/processes aynı anda full-size temp yazamıyordu; V4
thread RLock'u da açıkça ekler. Farklı final dosyaları paralel yazılabilir.
Normal exception ve graceful SIGTERM cleanup yapar; SIGKILL finally çalıştıramaz.
Bu yüzden bütün eski temp'lerin nedenini “finally yok” veya “aynı final race”
olarak açıklamak doğru değildir. Testte hard kill orphan bırakır; sonraki
proof turu yalnız gerçek içerik kanıtıyla siler.

GitHub `main.yml` her 30 dakikada main'e veri commit/push yapıyordu; Git history'de
“BIST verisini otomatik güncelle” commitleri bulunur. GitHub main auto-deploy
bağlantısıyla bu bir deploy döngüsüdür. Supervisor 25s grace ardından kill eder;
üretimdeki her orphan'ın bu kill'e ait olduğu log olmadan söylenemez. Workflow
artık contents:read + ayrı artifact/3 gün retention kullanır; runtime veri güncellemesi
source branch'i değiştirmez. Railway ayarı bu görevde incelenmedi/değiştirilmedi.

## V4 yazım sözleşmesi

- Large threshold: 1 MiB. Tüm büyük writes exact streaming preflight/space guard
  ile temp ayırmadan kontrol edilir. CRITICAL'de reserve 32 MiB WAL + 8 MiB safety,
  normalde mevcut 1 MiB reserve; küçük writes 4 KiB reserve. WAL gerçek mevcut
  disk kullanımının içinde ayrıca hesaba katılır; guard alan ayırmaz, ENOSPC yarışına
  karşı finally cleanup ve başarısızlık raporu korunur.
- Aynı AI-history rows/order/root alanları değişmemiş ve root guncelleme geçerli,
  monoton ise SKIP_UNCHANGED_WRITE: inode/clock/final bytes değişmez. Root clock
  yazım saati sayılır; gerçek snapshot/sinyal fiyat/timestamp alanları normalize
  edilmez. Diğer büyük dosyalarda yalnız byte-identical içerik skip edilir.
- CRITICAL >=90% veya headroom yetersiz olduğunda **yalnız canonical private
  AI history** küçük durable WAL'a değişiklik intent'i yazar, büyük temp oluşturmaz.
  Caller'a STORAGE_PENDING/ENOSPC açıkça döner: canonical JSON güncellenmiş gibi
  false acknowledgement verilmez. Mevcut JSON consumers değiştirilmedi, stale
  canonical sonuçları pending olayların işlendiği şeklinde tanıtılmaz.
- WAL mevcutsa sonraki intentler de aynı queue'ya eklenir. Headroom ve occupancy
  normale dönünce maintenance tüm doğrulanmış intentleri tek atomic streaming
  merge ile canonical JSON'a taşır. Critical modda merge de bekler; devam eden
  forensic'in final fingerprint'ini her tur bozan yeni dev write başlatmaz.
  **Normal disk durumunda gerçekten değişmiş synchronous JSON writes hâlâ tek
  full rewrite yapar.** Her legacy API çağrısını global olarak geciktirmek güvenli
  read-your-writes sözleşmesini bozar; bu release böyle bir migration yapmaz.
- `.ai-history-pending-v4.wal` private/runtime, en çok 32 MiB, transaction 8 MiB;
  sequence/checksum/append fsync/directory fsync. CAS field chains, idempotent
  replay ve conflict retention; torn/corrupt WAL asla truncate edilmez.
  Yeni sıra/omitted alan/row silme intent'i üretilmez; önceki history saklanır.
  Limit/conflict/fsync başarısızlığında explicit backpressure; sessiz data-drop yok.
  Önceden var olan legacy 100,000-record producer cap değiştirilmedi. Critical
  WAL merge omitted eski rows'u silmez; unique eski orphan kayıtları da korunur.
- Cache replay üretimi critical modda skip edilir; unique bar/history/snapshot/user
  verisi disposable kabul edilmez. Büyük yeni unique JSON headroom yetersizse
  explicit hata verir; başka datasetler körlemesine WAL'a dönüştürülmedi.
- SIGTERM large-write gate'i kapatır; encode/read/write chunk aralarında cancel,
  own temp cleanup, lease release. Küçük transactions bitirilebilir. 25s supervisor
  veya kernel-I/O/SIGKILL kesintisinin mutlak önlenmesi garanti edilmez.

## Resumable proof ve alan hedefi

`runtime/disk_forensic_checkpoint.json`: checksummed metadata, max 256 KiB,
128 temp states, 8 final-index states. inode/size/mtime/dev değişirse reset.
Byte offset prefix/suffix/exact; semantic final-index/parser root phase ve record
byte offsets/identity/frozen/outcome hashes ile gerçekten kaldığı yerden sürer.
History payload checkpoint'e kopyalanmaz. SQLite proof indexes `/tmp` üzerinde,
256 MiB aggregate checked bound ve per-index 64 MiB page cap; yalnız doğrulanmış
ownership marker'lı stale proof indexes kaldırılır. Missing index compare progress'i
reset eder. Disk küçük CP'yi bile yazamıyorsa progress kaydı başarısızlığı görünür,
hiçbir temp bu yüzden silinmez. Unknown/symlink CP dosyası üzerine yazılmaz.

Startup 180s, maintenance 60s/300s budgets korunur. Fairness dört turda large /
unfinished oldest / aged / smallest sırasını döndürür; küçük dosyalar sürekli
büyük dosyanın gerisinde kalmaz. Dosya lease/worker scope/foreign-open/target locks
ve fingerprints tekrar doğrulanır; yalnız PROVEN_REDUNDANT, PROVEN_SUBSET_OF_FINAL,
PROVEN_OLDER_COMPLETE_COPY silinir. ACTIVE/UNKNOWN/UNIQUE ve immutable finals
silinmez. İlk 64KiB schema hint + hashed filename target discovery sağlar;
hint deletion proof değildir. Yeni sidecar <=4096 byte target/writer/creation/
transaction/inode/state içerir, prediction/user payload içermez. Sidecar ancak
paired payload içerik kanıtıyla kaldırılmışsa ve metadata doğrulanmışsa temizlenir.

Free 1 GiB (tercihen 2 GiB) hedefi sınıflandırma güvenliğini gevşetmez. Alan
hedefi sağlanamıyorsa health/log açık kalır; UNKNOWN'u silerek hedef sağlanmaz.
Büyük JSON'lar normal durumda kendi değişen tarihçelerinin büyüklüğü kadar tek
scratch gerektirir; bu release “disk asla dolamaz” garantisi vermez.

## Gözlem

STORAGE_WRITE_TRACE: writer module:function, target hash, dataset, reason,
logical_changed_bytes, physical_temp_bytes, final_size, timestamps, duration,
success, temp_removed, free_before/after. AI synchronous logical metric changed
**row payload** bytes'tır (tam byte-diff değildir); ölçülemeyen diğer datasets için
None yazılır, sahte sayı verilmez. WAL/stress delta metric CAS operation payload
bytes'tır. Filesystem block/journal amplification ayrıca ölçülmüş değildir.

Lifecycle CREATED/WRITING/FSYNCED/READY_TO_RENAME/RENAMED/CLEANED/ABORTED/ORPHANED.
STORAGE_GROWTH yaklaşık 300s kadans + elapsed_seconds: free/temp/new/removed
counts ve bytes, interval-delta largest_writer. Yaşı >=300s retained/growing temp
ve başarılı karşılık rename yoksa STORAGE_LEAK_ALERT writer/target/age/txncount.
Eski meta olmayan dosyalarda UNKNOWN kullanılır, içerikten kullanıcı kimliği
çıkarılmaz. State/stats max256targets; logs stdout/stderr, persistent log dosyası
ve yeni sınırsız backup oluşturulmaz. İlk gözlem 5m geçmişi olmadığı için null'dır.

## Statik caller envanteri

`U` = ortak atomic_json/atomic_write_json → `.user-*`; `S` = json_atomik_yaz
→ `.snapshot-*`; `M` = copy_new → `.migration-*`. Aşağıdaki hedef expressions
kaynak koddan gelir; değişkenlerin gerçek final byte ölçümü STORAGE_WRITE_TRACE ile
alınır. 275+ MB history boyutu yalnız kullanıcının production ölçümüdür; diğer
boyutlar için production incelemeden kesin MB iddia edilmez.

U/S ortak sözleşme: thread+target flock, finally cleanup EVET; large SIGTERM
chunk-cancel, SIGKILL ancak sonraki proof; changed full rewrite EVET (AI critical
pending WAL hariç); **aynı final concurrent full temp HAYIR**. M sözleşme:
folder flock+create-only, finally EVET, SIGKILL .migration scratch olabilir;
existing final overwrite HAYIR, boot copy yalnız hedef yokken. Bu alanlar her
satır için uygulanır; wrapper caller'ın kendi RMW business lock'u ayrıca korunur.

| Writer | Caller (line) | Final target expression | Estimated size | Frequency | Lock | Finally | SIGTERM | SIGKILL | Whole file | Concurrent same-final |
|---|---|---|---|---|---|---|---|---|---|---|
| U: atomic_json | ai_karar_motoru.py:AIKararMotoru.weights:530 | `self.weight_path` | veriye bağlı; trace/stat | AI batch başına; priority ≤3/2s, full_scan batch/30s; ek çağrılar mümkün | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ai_karar_motoru.py:AIKararMotoru.update_weights:556 | `self.weight_path` | veriye bağlı; trace/stat | AI batch başına; priority ≤3/2s, full_scan batch/30s; ek çağrılar mümkün | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ai_karar_motoru.py:AIKararMotoru.batch:654 | `self.history_path` | 275+ MB (production supplied) | AI batch başına; priority ≤3/2s, full_scan batch/30s; ek çağrılar mümkün | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ai_karar_motoru.py:AIKararMotoru.batch:655 | `self.baseline_path` | veriye bağlı; trace/stat | AI batch başına; priority ≤3/2s, full_scan batch/30s; ek çağrılar mümkün | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ai_karar_motoru.py:AIKararMotoru.batch:658 | `self.public_path` | veriye bağlı; trace/stat | AI batch başına; priority ≤3/2s, full_scan batch/30s; ek çağrılar mümkün | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ai_karar_motoru.py:AIKararMotoru.measure:682 | `self.history_path` | 275+ MB (production supplied) | AI batch başına; priority ≤3/2s, full_scan batch/30s; ek çağrılar mümkün | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ana_motor.py:AnaMotor.persist:146 | `self.directory / 'ana_motor_durum.json'` | veriye bağlı; trace/stat | heartbeat/tick (~1s) | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ana_motor_gorevleri.py:WorkerTasks.save_queue:65 | `self.queue_path` | veriye bağlı; trace/stat | ilgili task/event; priority 2s, bootstrap/full_scan 30s | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ana_motor_gorevleri.py:WorkerTasks.record_unsupported:124 | `path` | veriye bağlı; trace/stat | ilgili task/event; priority 2s, bootstrap/full_scan 30s | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ana_motor_gorevleri.py:WorkerTasks.bootstrap:183 | `self.directory / 'public_bootstrap_complete.json'` | veriye bağlı; trace/stat | ilgili task/event; priority 2s, bootstrap/full_scan 30s | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ana_motor_gorevleri.py:WorkerTasks.bootstrap:187 | `self.directory / 'public_bootstrap_complete.json'` | veriye bağlı; trace/stat | ilgili task/event; priority 2s, bootstrap/full_scan 30s | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | ana_motor_gorevleri.py:WorkerTasks.tomorrow:222 | `checkpoint` | veriye bağlı; trace/stat | ilgili task/event; priority 2s, bootstrap/full_scan 30s | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | bist_bot.py:tahmin_gecmisi_yaz:99 | `Path(dosya_yolu or TAHMIN_GECMISI_FILE)` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | bist_bot.py:web_verisi_kaydet:1936 | `Path(DATA_FILE)` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: atomic_write_json | bist_bot.py:json_atomik_yaz:2119 | `dosya` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:yarin_top10_kilitli_kaydet:2217 | `eski_arsiv` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:yarin_top10_kilitli_kaydet:2224 | `YARIN_TOP10_FILE` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:yarin_top10_kilitli_kaydet:2294 | `arsiv` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:yarin_top10_kilitli_kaydet:2296 | `YARIN_TOP10_FILE` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:yarin_top10_canli_guncelle:2431 | `YARIN_TOP10_CANLI_FILE` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:ai_ogrenme_kaydet:4732 | `dosya` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:ai_sinyal_sonuc_guncelle:5348 | `dosya` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:gun_ici_top10_tara:5533 | `web_dosya` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:gun_ici_top10_tara:5550 | `tum_web_dosya` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| S: json_atomik_yaz | bist_bot.py:gun_ici_top10_tara:5639 | `YARIN_TOP10_CANLI_FILE` | veriye bağlı; trace/stat | tarama/sinyal/event; intraday 300s, yarın after-close | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | canli_motor.py:durum_yaz:65 | `DURUM_DOSYA` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | canli_motor.py:oncelikli_hisse_guncelle:441 | `data_file` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| M: copy_new | cloud_bootstrap.py:_bootstrap_public:48 | `target` | veriye bağlı; trace/stat | başlangıç/create-if-missing | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| M: copy_new | cloud_bootstrap.py:_bootstrap_public:52 | `target` | veriye bağlı; trace/stat | başlangıç/create-if-missing | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| M: copy_new | cloud_bootstrap.py:_bootstrap_public:57 | `location.archives / (day + '.json')` | veriye bağlı; trace/stat | başlangıç/create-if-missing | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| U: atomic_json | cloud_bootstrap.py:_bootstrap_public:64 | `location.public / 'yarin_top10.json'` | veriye bağlı; trace/stat | başlangıç/create-if-missing | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| M: copy_new | cloud_bootstrap.py:_bootstrap_public:74 | `target` | veriye bağlı; trace/stat | başlangıç/create-if-missing | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| U: atomic_json | disk_forensik.py:write_manifest:170 | `target` | veriye bağlı; trace/stat | silme sonrası bounded manifest | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | disk_koruma.py:save_price_cache:91 | `path` | veriye bağlı; trace/stat | startup/cache güncellemesi | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | disk_koruma.py:reclaim_once:205 | `marker` | veriye bağlı; trace/stat | startup/cache güncellemesi | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | disk_koruma.py:reclaim_once:254 | `marker` | veriye bağlı; trace/stat | startup/cache güncellemesi | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | disk_resumable.py:ResumableProof.save:91 | `self.path` | <=256 KiB | startup ve 300s maintenance | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | fiyat_alarm_motoru.py:alarmlari_kontrol_et:231 | `path` | veriye bağlı; trace/stat | 30s varsayılan; tetikleme olduğunda | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.cache_bars:165 | `self.bars_file` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.record:231 | `self.file` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.signal_round:319 | `target` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.signal_round:320 | `control_path` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.one_round:369 | `self.file` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.publish_and_learn:403 | `self.weights_file` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.publish_and_learn:450 | `self.location.public / 'gun_ici_performans.json'` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gun_ici_performans.py:GunIciPerformans.publish_and_learn:453 | `self.location.public / 'gun_ici_onerilen_agirliklar.json'` | veriye bağlı; trace/stat | 300s task / event / rapor | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gunluk_al_sat.py:GunlukAlSat.persist:207 | `target` | veriye bağlı; trace/stat | mevcut 5m worker task | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gunluk_al_sat.py:GunlukAlSat.one_round:260 | `self.state_path` | veriye bağlı; trace/stat | mevcut 5m worker task | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gunluk_al_sat.py:GunlukAlSat.one_round:263 | `target` | veriye bağlı; trace/stat | mevcut 5m worker task | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | gunluk_al_sat.py:GunlukAlSat.one_round:272 | `self.public_path` | veriye bağlı; trace/stat | mevcut 5m worker task | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews._publish:127 | `self.public_path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews._history:141 | `self.history_path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews.process:175 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews.process:182 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews.process:186 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews.process:198 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_tekillestirme.py:CanonicalNews.process:199 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_zeka.py:_save:97 | `Path(HABER_FILE)` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | haber_zeka.py:haber_kaydet:299 | `target` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | intraday_sinyal_performansi.py:publish:304 | `target` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | kap_canli.py:durum_yaz:148 | `DURUM_DOSYA` | veriye bağlı; trace/stat | 60s task + event | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | kap_canli.py:web_alarm_kaydet:401 | `output_path` | veriye bağlı; trace/stat | 60s task + event | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_write_json | kullanici_kayitlari.py:atomic_json:57 | `path` | veriye bağlı; trace/stat | HTTP kullanıcı işlemi, create-if-missing | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | kullanici_kayitlari.py:UserRecords.locked:81 | `path` | veriye bağlı; trace/stat | HTTP kullanıcı işlemi, create-if-missing | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | kullanici_kayitlari.py:UserRecords.save_levels:98 | `path` | veriye bağlı; trace/stat | HTTP kullanıcı işlemi, create-if-missing | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | kullanici_kayitlari.py:UserRecords.create_alarm:186 | `path` | veriye bağlı; trace/stat | HTTP kullanıcı işlemi, create-if-missing | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | kullanici_kayitlari.py:UserRecords.change_alarm:202 | `path` | veriye bağlı; trace/stat | HTTP kullanıcı işlemi, create-if-missing | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | makro_ai.py:canli_makro_etki_yaz:413 | `CANLI_MAKRO_DOSYA` | veriye bağlı; trace/stat | 120s task + event | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | makro_ai.py:canli_makro_etki_yaz:434 | `MAKRO_GECMIS` | veriye bağlı; trace/stat | 120s task + event | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | makro_kaynak.py:_save:54 | `path` | veriye bağlı; trace/stat | 120s task / yeni kaynak | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.reports:483 | `self.result_path` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.reports:487 | `self.location.public / name` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.reports:489 | `target` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.one_round:521 | `self.history_path` | 275+ MB (production supplied) | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.one_round:540 | `self.legacy_path` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.one_round:577 | `self.history_path` | 275+ MB (production supplied) | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.one_round:590 | `self.legacy_path` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:PerformansMotoru.one_round:597 | `self.state_path` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:decision_diagnostics:1182 | `target` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:decision_diagnostics:1193 | `target` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:controlled_publish:1319 | `file` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | performans_motoru.py:controlled_publish:1326 | `target` | veriye bağlı; trace/stat | performance varsayılan 900s; history turda 2 çağrı | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh:257 | `self.file` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_measurement:291 | `universe_path` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_measurement:299 | `target` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_measurement:311 | `idx_path` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_measurement:324 | `history` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_measurement:328 | `target` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_sectors:376 | `path` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_sectors:404 | `history` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:PiyasaBaglami.refresh_sectors:412 | `target` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:sector_indices:918 | `target` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:sector_indices:938 | `target` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:sector_benchmark:970 | `target` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | piyasa_baglami.py:sector_bootstrap:1000 | `path` | veriye bağlı; trace/stat | context/regime/sector 300s; bootstrap | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | pozitif_kapanis.py:publish_performance:369 | `path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | pozitif_kapanis.py:publish_performance:377 | `path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | push_bildirim_motoru.py:subscription_save:107 | `path` | veriye bağlı; trace/stat | 20s varsayılan; event/subscription değişikliği | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | push_bildirim_motoru.py:subscription_disable:117 | `path` | veriye bağlı; trace/stat | 20s varsayılan; event/subscription değişikliği | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | push_bildirim_motoru.py:bildirimleri_gonder:175 | `path` | veriye bağlı; trace/stat | 20s varsayılan; event/subscription değişikliği | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | push_bildirim_motoru.py:bildirimleri_gonder:203 | `sub_path` | veriye bağlı; trace/stat | 20s varsayılan; event/subscription değişikliği | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | push_bildirim_motoru.py:bildirimleri_gonder:211 | `path` | veriye bağlı; trace/stat | 20s varsayılan; event/subscription değişikliği | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sinyal_performansi.py:publish:289 | `target` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sinyal_performansi.py:refresh_indicator_performance:833 | `public` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sinyal_performansi.py:refresh_indicator_performance:834 | `target` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sinyal_performansi.py:refresh_indicator_performance:840 | `archive` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._pace:109 | `self.path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._robots:138 | `self.path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._process:185 | `self.path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._deliver:204 | `self.public_path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._deliver:206 | `self.path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._round:280 | `self.path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | sirket_site_motoru.py:SirketSiteMotoru._round:323 | `self.path` | veriye bağlı; trace/stat | 900s task + kaynak geçiş checkpointleri | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | top10_ogrenme_performansi.py:publish:150 | `target` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| M: copy_new | veri_yollari.py:migrate:145 | `target` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| M: copy_new | veri_yollari.py:migrate:147 | `destination.archives / source.name` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| M: copy_new | veri_yollari.py:migrate:148 | `destination.users / source.name` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| M: copy_new | veri_yollari.py:migrate:149 | `destination.runtime / source.name` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| M: copy_new | veri_yollari.py:migrate:150 | `destination.runtime_file(name)` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | folder flock | evet | copy finally; hardkill riski | proof required | create-only copy | hayır |
| U: atomic_json | yarin_kalibrasyon.py:YarinKalibrasyon.refresh:185 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | yarin_kalibrasyon.py:YarinKalibrasyon.refresh:186 | `self.history` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | yarin_kalibrasyon.py:YarinKalibrasyon.freeze_day:206 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | yarin_kalibrasyon.py:YarinKalibrasyon.rollback:213 | `self.path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | yarin_kalibrasyon.py:YarinKalibrasyon.publish:231 | `self.location.public / 'kalibrasyon_durumu.json'` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |
| U: atomic_json | yarin_plani.py:get_plan:212 | `path` | veriye bağlı; trace/stat | ilgili event/rapor; sabit frekans yok | thread + target flock | evet | large chunk gate + finally | proof required | changed: evet | hayır |

Static call sites: {'U': 105, 'S': 11, 'M': 9}; fiziksel `.user-*` allocator **1**.

## Validation (2026-10-08, isolated test volumes)

- New V4 unit tests: 59. Storage suite: 237 (52 atomic + 59 forensic +
  17 disk + 13 reclaim-once + 37 V3 + 59 V4), all pass. Existing hard-kill
  subprocess, graceful SIGTERM, multiprocess locks and worker-scope tests are
  included; not just mocked boolean checks.
- Full Python regression: 1621 passing tests; 18 JS/frontend smoke groups.
- Python syntax: 160 files; imports: 13 modules. JS syntax: 19 external files
  + one nonempty inline script. Offline --check and actual main with mocked
  adapters/providers, real scheduler/worker-lock/maintenance start/join pass.
- 17 protected calculation/provider/bootstrap modules are byte-identical to
  2e10b83e78f8d61a12c3dcdfae2ce246b7297055. No production path was accessed.

### Actual stress measurement

`tests/storage_stress_v4.py`: optional, creates and removes only its own temporary
volume; fixture is generated, not committed. Real 293,888,983-byte initial history
(280.27 MiB), 100,000 records; 100 distinct small updates. Normal baseline full
commit is measured once; 100 baseline rewrites below are an **arithmetic
extrapolation**, not an assertion that 29GB of writes were performed. The WAL
100 transactions and the single merged rewrite are actually performed.

```json
{
  "initial_bytes": 293888983,
  "logical_delta_bytes": 20490,
  "wal_bytes": 33082,
  "merge_temp_bytes": 293894173,
  "physical_payload_bytes": 293927255,
  "amplification": 14344.91,
  "baseline_100_rewrites_theoretical_bytes": 29388898300,
  "baseline_theoretical_amplification": 1434304.46,
  "max_temp_files": 1,
  "max_temp_bytes": 293894173,
  "remaining_temp_files": 0,
  "updated_records": 100,
  "retained_records": 100000,
  "coalesced_transactions": 100
}
```

Physical payload includes WAL + merged JSON, excludes small sidecar, directory
metadata, filesystem block/journal overhead and the initial fixture creation.
Logical changed bytes are checksum/CAS delta-operation payload (20,490 bytes),
not only the new floating-point return value. A compatible flat JSON still costs
~280MiB per real merged commit; measured payload amplification is 14,344.91x.
The theoretical 100-rewrite baseline is 1,434,304.46x, approximately a 100x
reduction by batching. No uncontrolled full-size temp accumulation occurred.
Normal synchronous changed legacy calls outside storage pressure are **not**
claimed to achieve this batch result; critical/pending WAL and explicit delta
batches do. Production 1GiB/2GiB free targets and deployment success must be
verified externally after main push; Railway was intentionally not contacted.
