# V6 salt okunur envanter ve kapasite tahmini — 2026-10-09

Bu geliştirmede production volume okunmadı; gerçek production boyutu, kayıt sayısı ve kapasite yeterliliği doğrulanmış değildir. Aşağıdaki araç yalnız açıkça verilen yerel/offline depolama kopyasında dosya metadata'sını okur. SQL/R2 bağlantısı, migration, recovery, cleanup, compression, içerik okuma, rapor dosyası yazımı veya dizin oluşturma çağırmaz. JSON raporu yalnız stdout'a basar. Python bytecode yazımını da kapatmak için `-B` kullanılır:

```
python -B -m v6_storage inventory --root /yetkili/offline-depolama-kopyasi
```

`--root` zorunludur; `BIST_DATA_DIR`, PostgreSQL DSN veya R2 anahtarları hedef seçmez. Production worker'ın startup veya bakım akışına bağlanmadı. Varsayılan legacy/shadow/postgres modu değiştirilmedi. Çıktıyı dosyaya yönlendirmek ayrı ve açık kullanıcı işlemidir; araç kendisi çıktı dosyası oluşturmaz.

## Ayrı veri grupları

| Grup | Örnek / koruma |
|---|---|
| prediction_history | Tahmin geçmişi, tarihli Yarın TOP10 snapshotları; korunur |
| learning_data | AI öğrenme, haber/makro öğrenme hafızası; korunur |
| signal_outcomes | Sinyal/performans sonuçları ve mum kayıtları; korunur |
| temporary_files | `.user-*`, yarım kopyalar ve temp dosyalar; benzersiz olabilir, korunur |
| recovery_records | V5 recovery/WAL ve forensic checkpoint kayıtları; korunur |
| private_user_data | Kullanıcı seviyeleri, alarmlar, subscription/queue; R2 senaryosuna dahil edilmez |
| reproducible_cache_review | Adında cache geçenler; yeniden üretilebilirlik ispatlanmış değildir, silinmez |
| other_preserve | Tanınmayan dosyalar; korunur |

Sınıflandırma dosya adı/dizin temelli ön envanterdir; JSON şeması, duplicate kaydı veya temp dosyanın hedef ilişkisi doğrulanmaz. Gerçek tahmin ile sonuç ayrımı bazı birleşik JSON'larda ancak gelecekte ayrıca yetkilendirilmiş içerik analiziyle yapılabilir. Her grupta adet, logical byte, allocated byte ve private byte raporlanır. Büyük dosyalar kimlik yerine hash token ile gösterilir. Hardlink alias'ları disk toplamında bir kez sayılır; kategori logical byte'ları alias/duplicate içerebilir ve kapasite girdisi olarak muhafazakârdır. Symlink ve özel dosyalar okunmaz. Okunamayan dizin/dosya varsa `complete=false`, hata sayısı ve CLI exit code 2 üretilir. Eşzamanlı değişen canlı dizin için atomik snapshot doğruluğu iddia edilmez.

## PostgreSQL / R2 varsayımları

`H`: private olmayan prediction/learning/signal-outcome JSON logical byte toplamı. PostgreSQL depolama senaryosu `H × 1.5–3.0`'dır. Katsayılar tablo/JSONB/index overhead'i için doğrulanmamış planlama varsayımlarıdır; dedup sonrası gerçek unique kayıt sayısı, WAL, backup ve replica gereksinimi bilinmez. `measured_database_bytes` ve `unique_record_count` null kalır. `.json/.jsonl` dışındaki veya sıkıştırılmış geçmişler bu PG girdisine dahil edilmez; temp/recovery içindeki henüz doğrulanmamış benzersiz kayıtlar ayrıca `unresolved_source_bytes` olarak tutulur. Bunların açılmış boyutu veya gerçek records sayısı bilinmediğinden toplam cutover ihtiyacı (`estimated_total_cutover_bytes`) null kalır.

`A`: private olmayan bütün prediction/learning/signal dosyaları + temp/recovery/unknown logical byte toplamı (JSON dışında sıkıştırılmış arşivler de dahil). Bunlar otomatik arşivlenebilir ilan edilmez; benzersiz verinin korunması için gelecekteki R2 karantina/arşiv bütçesinde ayrı gösterilir. Adı `.gz/.zip/.bz2/.xz/.zst` ile biten dosyalar mevcut boyutlarıyla ayrı sayılır; bunların bir kez daha sıkışacağı varsayılmaz. Kalan baytlar için varsayılan R2 senaryosu `0.25–0.75×`'dir; sıkıştırılmış biçim de içerik okunmadığı için doğrulanmamıştır. Sıkıştırma ölçülmedi; sıkıştırılamayan içerik ve gzip/object overhead'i için bu aralık üst sınır garantisi değildir. Daha ihtiyatlı senaryo için `--r2-ratio-high 1` seçilebilir; gerçek arşiv formatı, overhead ve yedek kopya sayısı ayrıca ölçülmelidir. Private temp dahil bütün private dosyalar bu R2 senaryosundan çıkarılır.

| Varsayımsal ham giriş (decimal GB) | PG 1.5–3× | R2 .25–.75× |
|---|---|---|
| 5 GB | 7.5–15 GB | 1.25–3.75 GB |
| 10 GB | 15–30 GB | 2.5–7.5 GB |
| 25 GB | 37.5–75 GB | 6.25–18.75 GB |
| 50 GB | 75–150 GB | 12.5–37.5 GB |
| 100 GB | 150–300 GB | 25–75 GB |

PG ve R2 girişleri farklıdır; tablodaki aynı ham boyut ikisinin birlikte gerçek gereksinimi olduğu anlamına gelmez. Bu kapasite senaryoları fiyat değildir; güncel fiyat/bütçe doğrulanmadı, ücretli kaynak oluşturulmadı. Mevcut $10 aylık ek bütçeye uygunluk kanıtlanmış değildir. `--pg-factor-low/high` ve `--r2-ratio-low/high` ile varsayımlar açıkça değiştirilebilir; hiçbir storage backend değişimi yapılmaz.

## Doğrulama

Geçici fixture üzerinde sınıflandırma/hesap, içerik okuma yasağı, byte+mtime değişmezliği, private temp hariç tutma, symlink/hardlink, eksik hedef, hatalı katsayı, okunamayan dizin ve ortam değişkenlerinden bağımsız CLI test edildi. Production verisi test fixture olarak kullanılmadı. Mevcut V5 journal/proof mekanizmaları ve canlı storage writer'ları değiştirilmedi.

`STORAGE_V6_REPOSITORY_INVENTORY.json` eki yalnız yerel repo `webapp/data` metadata ölçümüdür; production veya tam `.local` envanteri değildir. Kaynak boyut/mtime değerleri değişmedi. Gerçek production kapasitesi ölçülmüş değildir.

## İnternete kapalı, tek seferlik Railway log envanteri

HTTP yönetici endpoint’i kaldırılmıştır; eski adres her API metodunda 404 verir.
Yönetici anahtarı gerekmez. Mevcut Railway yönetici erişimiyle servisin çalışan
container'ında (Railway SSH/exec oturumu, deployment build shell değil) yalnız bir kez:

```sh
python -B -m v6_storage inventory-log --railway-logs
```

Komut `BIST_DATA_DIR` değerini kullanır (production `/data`); varsayılan yerel yol
veya kullanıcıdan gelen dosya yolu yoktur. Bir turdan sonra çıkar, scheduler,
başlangıç hook'u, otomatik retry, kalıcı marker veya rapor dosyası oluşturmaz.
Her manuel çağrı yeni bir turdur; restart/deploy çağrıyı tekrarlamaz.
`--railway-logs` çıktıyı mevcut `/proc/1/fd/1` container stdout pipe'ına yazar:
`[V6_INVENTORY]` satırı Railway servis loglarında aranabilir. stdout pipe değilse
veya yazılamıyorsa exit 2 verir; diske fallback yoktur. Çıkış kodunu kontrol edin.
Yerel testte flagsiz çağrı yalnız çağıran terminale çıktı verir.

Kategori bazlı adet/byte toplamları ve PG/R2 varsayımsal aralıkları loglanır;
dosya adları, yolları, tokenlar, içerik veya kullanıcı kimlikleri loglanmaz.
Raporlar özel Railway proje loglarında kalmalıdır. PG/R2 bağlantısı kurulmaz.
Symlinkler izlenmez. Tarama 200.000 girdi, 64 dizin derinliği ve kooperatif
20 saniyelik bütçeyle sınırlıdır; filesystem çağrısı bloklanırsa katı timeout yoktur.
`complete=false`/exit 2, toplamların kısmi olduğunu gösterir. Metadata sınıflandırması
kesin kayıt sayısı değildir; canlı yazımlar nedeniyle atomik snapshot değildir.
Hiçbir cleanup, migration, recovery veya kaynak değişikliği yapılmaz. Bu geliştirmede
production üzerinde çağrı yapılmamış, gerçek volume kapasitesi ölçülmemiştir.
