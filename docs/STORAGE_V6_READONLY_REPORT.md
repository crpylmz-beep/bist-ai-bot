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

## Korunan production yönetici çağrısı

Mevcut web sunucusunda `POST /api/admin/storage-inventory` uç noktası vardır.
`BIST_STORAGE_ADMIN_TOKEN` en az 32 ASCII karakterlik ayrı, rastgele bir secret olarak
Railway Variables üzerinden operatör tarafından tanımlanmalıdır. Tanımsız/kısa anahtar
mekanizmayı kapalı tutar (503). Anahtarı repoya, URL'ye veya loglara yazmayın.
Yalnız HTTPS üzerinden `Authorization: Bearer <secret>` başlığı gönderilir; istek
parametresiz ve gövdesiz olmalıdır. Tarayıcı oturum çerezi yönetici yetkisi vermez.
Yanıta CORS izni verilmez; Origin taşıyan tarayıcı çağrıları reddedilir.

Operatör, anahtarı güvenli ortamına aldıktan sonra aşağıdaki Python istemcisiyle
çağırabilir; komut satırına secret koymaz, yalnız toplu raporu standart çıktıya basar:

```python
import os, urllib.request
request = urllib.request.Request(
    os.environ['BIST_PUBLIC_HTTPS_URL'].rstrip('/') + '/api/admin/storage-inventory',
    method='POST', headers={'Authorization': 'Bearer ' + os.environ['BIST_STORAGE_ADMIN_TOKEN']})
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.read().decode('utf-8'))
```

Sunucunun yapılandırılmış `BIST_DATA_DIR` kökü kullanılır (production için `/data`);
istemde yol seçilemez. Envanter veri klasörü oluşturmaz, recovery/cleanup/migration
çalıştırmaz ve rapor dosyası yazmaz. Tek tarama eşzamanlı çalışır; en az 60 saniye
ara gerekir. En fazla 200.000 dizin girdisi, 64 dizin derinliği ve 20 saniyelik
kooperatif tarama bütçesi uygulanır (tek bir filesystem çağrısı bloklanırsa bu süre
katı bir wall-clock timeout değildir). Symlinkler izlenmez. Sonuç yalnız kategori
sayı/boyutları, disk toplamları ve varsayımsal PostgreSQL/R2 aralıklarını içerir;
dosya adları, yolları, içerikleri veya kullanıcı kimlikleri dönmez.
`complete=false` durumunda 206 döner; kısmi toplamlar tüm volume ölçümü değildir.
Canlı dosyalar eşzamanlı değişebilir, sonuç atomik snapshot değildir. Bu geliştirme
sırasında production çağrısı yapılmamış ve gerçek `/data` kullanımı ölçülmemiştir.
