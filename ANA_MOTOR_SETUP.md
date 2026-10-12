# Ana koordinasyon motoru

`ana_motor.py` yerel veya ayrı cloud worker süreci için hazırlanmıştır. Deployment, servis kurulumu ve otomatik başlatma yapılmadı. Aynı çalışma dizininde ikinci koordinatör dosya kilidiyle engellenir. Eski `canli_motor.motoru_calistir`, KAP/makro sonsuz döngüleri veya eski tarama cron’ları bu worker ile birlikte çalıştırılmamalıdır.

## Çalıştırma

Repo kökünde bağımlılıkları requirements.txt ile kurun. Önce `python ana_motor.py --check` çalıştırın: import/config kontrolüdür, piyasa taraması ve push göndermez. Sonra `python ana_motor.py` ayrı worker sürecidir. Web ayrı olarak `python web_server.py` çalışır. Ctrl+C/SIGTERM yeni işleri durdurur, kapanış taramasını mevcut küçük batch sonrasında keser ve başlamış diğer çağrıların bitmesini bekler. Başlamış Python thread’i zorla öldürülmez; provider timeout davranışı üretim öncesinde gözlenmelidir.

Mevcut Procfile `web: python web_server.py` olarak korundu. Gelecekte önerilen ayrım:

```
web: python web_server.py
worker: python ana_motor.py
```

Hosting sağlayıcısında bunlar ayrı process/service olarak tanımlanmalıdır; bu doküman deployment yapmaz. Web ve worker aynı kalıcı özel kullanıcı veri dizinini ve çalışma verilerini paylaşmalıdır. Ayrı makinelere bağımsız yerel kopyalarla dağıtmak kullanıcı alarm/outbox verisini ayırır; mevcut flock/atomic mimarisi tek worker ve paylaşılan POSIX dosya sistemi için tasarlanmıştır.

## Periyotlar ve eşzamanlılık

| Görev | Varsayılan | Environment |
|---|---:|---|
| KAP | 60 sn | KAP_INTERVAL_SECONDS |
| Makro | 120 sn | MACRO_INTERVAL_SECONDS |
| Fiyat alarmı | 30 sn | ALARM_INTERVAL_SECONDS |
| Push | 20 sn | PUSH_INTERVAL_SECONDS |
| Gün İçi TOP10 | 300 sn | INTRADAY_TOP10_INTERVAL_SECONDS |
| Şirket sitesi | 900 sn | COMPANY_SITE_INTERVAL_SECONDS |
| Tam tarama batch | 30 sn | FULL_SCAN_INTERVAL_SECONDS |
| Öncelikli analiz kuyruğu | 2 sn | PRIORITY_INTERVAL_SECONDS |
| Yarın TOP10 uygunluk kontrolü | 60 sn | YARIN_TOP10_INTERVAL_SECONDS |

Periyot tamamlanan görevden sonra hesaplanır; aynı görev üst üste bindirilmez. Hata halinde exponential backoff uygulanır, en fazla 900 sn. En fazla 6 koordinatör thread’i ve 3 teknik fiyat thread’i vardır. Teknik tarama, öncelikli analiz, Gün İçi ve kapanış üretimi tek teknik hattı paylaşır; JSON yazımlarının birbiriyle yarışması önlenir. Diğer beş iş bu hat tarafından bekletilmez.

`FULL_SCAN_BATCH_SIZE` varsayılan 10, sınır 1–25. Bütün hisseler döner batch’lerle taranır; tamamlanma süresi hisse sayısı ve provider hızına bağlıdır. Başarısız hisseler öncelik kuyruğunda tekrar denenir. Öncelikli semboller birleştirilerek `.local/runtime/oncelik_kuyrugu.json` içinde saklanır. KAP ve makronun mevcut haber analiz fonksiyonları korunur; yalnızca senkron teknik tetikleri worker içinde kuyruğa yönlendirilir. Kuyruk teknik hat boşaldığında öncelik alır. Haber sonrası Gün İçi sıralama düzenli 5 dakikalık görevle yenilenir.

## Piyasa ve snapshot

Merkezi zaman dilimi Europe/Istanbul’dur. UTC sunucuda da hafta içi 10:00–18:10 piyasa açık kabul edilir; Gün İçi ve döner tam tarama bu aralık dışında yeni tur başlatmaz. Hafta içi 18:15 sonrası Yarın TOP10 üretilebilir. `holiday` callback’i ile ileride tatil/yarım gün takvimi eklenebilir; bu sürümde resmi tatil takvimi bağlı değildir.

Yarın TOP10 ayrı kapanış teknik taramasıyla mevcut algoritmadan üretilir. Veri kaynaklarının ciddi eksikliği (%80’den az başarılı analiz), gün değişimi veya kapanma halinde snapshot dondurulmaz. Günlük tamamlanma state’te tutulur; restart sonrasında günlük snapshot zaten varsa üretim atlanır. Mevcut immutable snapshot yazıcısı ikinci yazımı ayrıca engeller. Performans, alarm snapshot seviyeleri ve teknik puanlamalar değişmedi.

Şirket sitesi motoru mevcut resmi URL’leri 15 şirket/tur ile döner biçimde izler (`COMPANY_SITE_BATCH_SIZE`: 1–20). Resmi sayfa, yatırımcı ilişkileri, RSS/Atom, sitemap ve duyuru sayfaları aşamalı keşfedilir. RSS/Atom tercih edilir; ilk kaynak senkronizasyonu sessizdir. Yeni içerik mevcut haber AI analizine ve mevcut öncelikli hisse kuyruğuna bağlanır. Robots, domain rate limit, timeout, site backoff ve bounded keşif uygulanır. Ayrıntılar SIRKET_SITE_TAKIP.md’dedir.

## Health, private veriler ve ortam

`.local/runtime/ana_motor_durum.json`: motor durumu, heartbeat, görev başlangıç/başarıları, son hata sınıfı, son kontrol zamanları. `last_full_scan_batch` batch zamanıdır; `last_full_scan` tamamlanan tur zamanıdır. `/health` web durumunu ve bu güvenli görev özetini döndürür; ana motor yoksa veya heartbeat 30 sn’den eskiyse `healthy=false`. Kullanıcı kimliği, subscription, endpoint, secret ve bildirim içerikleri health yanıtına konmaz.

İsteğe bağlı `BIST_RUNTIME_DIR` ve `BIST_USER_DATA_DIR` özel kalıcı dizinlere ayarlanabilir. Kullanıcı verileri public webapp/data içine taşınmaz. Push için `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` gereklidir; eksiklik yalnızca push görevine hata/backoff verir. BOT_TOKEN ana motor için gerekli değildir. Ayrıntılar PUSH_SETUP.md’de.

## Deployment öncesinde

- Kalıcı POSIX veri dizinleri ve web/worker ortak dosya görünümü.
- VAPID secret’larının güvenli ortam ayarları; PWA için gerçek HTTPS ve iPhone Home Screen testi.
- Provider erişimi/rate limit/timeout, seans saatleri ve resmi tatil/yarım gün takvimi doğrulaması.
- Hosting process restart/supervision, SIGTERM grace süresi ve health alarmı.
- Eski cron/motor süreçlerinin kapatılması; tek aktif koordinatör.
- Gerçek KAP/RSS/site kaynaklarının staging’de kontrollü smoke kontrolü. Bu adımın testleri mock fiyat ve olaylar kullanır.

Testler: `python -m unittest discover -s tests -v`; mevcut JavaScript smoke testleri korunur. Teknik algoritma değişikliği yoktur; bağlı eski modüllerde import sırasında ağ çağrısı kaldırıldı ve gerekli JSON yazımları atomik hale getirildi.

## Ortak veri kökü (sekizinci adım)

Kalıcı volume için web ve worker’da aynı `BIST_DATA_DIR` kullanılır. Public, private, runtime ve archive ayrımı, migration ve volume örneği DATA_PERSISTENCE.md’de açıklanmıştır. Bu değişken tanımlıyken eski özel dizin override’ları yalnızca aynı alt dizinleri gösteriyorsa kabul edilir.

## Ortak AI karar bağlamı (on birinci adım)

Öncelikli analiz ve teknik batch sonrasında `ai_batch_guncelle` hazır analizlerden ortak özet üretir. Özel TOP10 puanı/snapshot değişmez; AI hatası diğer worker işleri durdurmaz. `LEARNING_ENABLED=false` varsayılan; otomatik optimizer yoktur. Ağırlık, tazelik, ölçüm ve ortak JSON/API modeli AI_KARAR_CORE.md’de açıklanmıştır.

## Performans görevi (on ikinci adım)

`performance`, `bekleyen_sonuclari_guncelle()` ile vadesi gelen açık sonuçları varsayılan 900 saniyede işler. PERFORMANCE_BATCH_SIZE=10 (1–25); tur başına en fazla 100 sinyal ve sembol başına tek geçmiş çağrısı. MIN_LEARNING_SAMPLES=40; LEARNING_ENABLED=false korunur, öneriler otomatik uygulanmaz. OHLC/işlem günü, kalite, rapor ve kalibrasyon ayrıntıları PERFORMANS_SETUP.md'de.

On üçüncü adımda aynı görev performans sonrasında `YarinKalibrasyon.refresh()` çağırır: katsayı önerisi günde bir kez, kapanış snapshot'ından önce ayrıca son kanıtla sabitlenir. Learning kapalıysa yalnız shadow etkilenir; aktivasyon otomatik değildir. Hata diğer görevleri durdurmaz. Limitler, rollback ve kayıt modeli YARIN_KALIBRASYON.md'de.

On dördüncü adımda ayrı `intraday_performance` görevi 300 saniyede çalışır (`INTRADAY_PERFORMANCE_INTERVAL_SECONDS`). Tek tur `bekleyen_gun_ici_sonuclari_guncelle()`; `GUN_ICI_PERFORMANCE_BATCH_SIZE=10`, `GUN_ICI_MIN_LEARNING_SAMPLES=40`, `GUN_ICI_LEARNING_ENABLED=false`. Ortak/Yarın learning flag'i Gün İçi learning'i açmaz. Sonuç/örnek/shadow ve çözünürlük kısıtları GUN_ICI_PERFORMANS.md'de.

On beşinci adımda `market_context` görevi 300 saniyede yalnız açık piyasada çalışır (`MARKET_CONTEXT_INTERVAL_SECONDS`). Mevcut tarama/endeks verilerini kullanır; ek fiyat/provider sorgusu yoktur. Tam Gün İçi tarama ve kapanış snapshot'ı kendi kaynak bağlamlarını aynı helper ile üretir. Etki ayarları ve safety kuralları PIYASA_BAGLAMI.md'de.

Cloud hazırlığı: Procfile artık web ve worker komutlarını içerir. Railway volume paylaşım sınırı nedeniyle uygulanabilir tek-volume/two-process başlangıcı `python cloud_baslat.py` olarak eklendi. Güncel gerçek kurulum ve sınırlar RAILWAY_DEPLOY.md'dedir; bu dokümandaki önceki “deployment yapılmadı” bilgisi geçerlidir.
