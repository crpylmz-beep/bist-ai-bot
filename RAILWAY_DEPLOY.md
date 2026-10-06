# Railway: kalıcı disk üzerinde web + worker

## Önce mimari sınırı

**İki ayrı Railway servisine tek Railway volume bağlanamaz.** Her servise ayrı `/data` volume eklemek ortak veri oluşturmaz; alarmlar, subscriptions ve heartbeat birbirinden kopar. Aynı `BIST_DATA_DIR` metnini yazmak aynı fiziksel diski paylaşmak değildir. Railway volumes kısıtları: https://docs.railway.com/guides/volumes . Bu hazırlık sırasında doküman adresi ortamın ağ proxy'sinden 403 verdi; dağıtımdan önce sağlayıcının güncel kısıtını tekrar kontrol edin.

Mevcut JSON/flock mimarisi için hazırlanmış uygulanabilir seçenek: **bir Railway servisi + bir volume + iki bağımsız process**. `cloud_baslat.py`, `python web_server.py` ve `python ana_motor.py` başlatır. Web restart olduğunda worker devam eder. Worker durursa servis hata koduyla çıkar; Railway servisi yeniden başlatır. SIGTERM her iki process'e iletilir, 25 sn sonunda bitmeyen process sonlandırılır. Atomik state diskte kalır; yarım kalmış provider çağrısı tamamlanmış sayılmaz. Tek replica kullanın, eski deployment bitmeden ikinci worker çalıştırmayın; worker flock kilidi ikinci worker'ı reddeder.

**İki Railway servisi şartsa henüz deployment-ready değildir:** paylaşılan transactional veri tabanına/storage'a geçiş ayrı çalışma gerektirir. Bu adımda yeni veritabanı, uzak JSON protokolü veya iki ayrı diskle sahte paylaşım eklenmedi. Ayrı process start command'leri Procfile'da hazır; ortak POSIX disk sağlayan başka bir ortamda ayrı servisler olarak kullanılabilir.

## Acemi kullanıcı için sıralı kurulum

1. railway.com'a GitHub ile giriş yapın; ücret/bütçe ve sürekli çalışacak planı kontrol edin.
2. Repo değişikliklerini inceleyip GitHub `main` branch'e gönderin. Bu görev commit/push veya gerçek deploy yapmadı.
3. Dashboard → **New Project → Deploy from GitHub repo**, `crpylmz-beep/bist-ai-bot` seçin. Servis adına `bist-web-worker` verin. Ayrı ikinci diskli worker servisi oluşturmayın.
4. **Settings → Build**: repodaki Dockerfile kullanılsın. Python 3.13, requirements sürümleri sabit. Start command `python cloud_baslat.py`. Railway TOML bu ayarları sağlar. İki alt process'in gerçek komutları `python web_server.py` ve `python ana_motor.py`.
5. Servise **Add Volume** (arayüzde proje canvas/New menüsünde bulunabilir) ile bir kalıcı volume ekleyin, mount path `/data` verin. Tek replica; Serverless/sleep kapalı olsun. Volume ve restart politikasıyla deployment kısa kesinti yaratabilir.
6. **Variables**: `BIST_DATA_DIR=/data` girin. Mount başka yerdeyse aynı gerçek yolu yazın. Railway'nin sağladığı `PORT` kullanılabilir; uygulama `0.0.0.0` dinler. `TZ=Europe/Istanbul` önerilir.
7. `.env.example` listesini referans alın. Learning flag'leri `false` bırakın. `BOT_TOKEN` zorunlu değildir.
8. Güvenilir yerel bilgisayarda repo bağımlılıkları kurulu iken `python vapid_uret.py` çalıştırın. Komutun terminalde gösterdiği `VAPID_PUBLIC_KEY` ve `VAPID_PRIVATE_KEY` değerlerini **yalnızca Railway Variables** alanlarına kopyalayın; private key otomatik dosyaya kaydedilmez. `VAPID_SUBJECT=mailto:gercek-adresiniz` girin. Private key'i chat'e, Git'e, ekran görüntüsüne veya log'a koymayın. Anahtarları her deploy'da yeniden üretmeyin; güvenli yedekleyin.
9. **Settings → Networking → Generate Domain**: HTTPS alan adı oluşturun. Uygulamanın tek kalıcı origin'ini kullanın; origin değişirse browser cookie/subscription yeniden kurulmalıdır.
10. **Deploy** yapın. `/`, `/manifest.webmanifest`, `/service-worker.js` HTTPS üzerinden 200 vermeli. Manifest/SW scope `/`; notification click `/?stock=THYAO` gibi aynı-origin detay açar. Service worker piyasa verisini cache'lemez.
11. Aynı deployment worker'ı da başlatır. Ayrı worker deploy düğmesi yoktur. **Logs** içinde `[WORKER] başladı` ve görev kayıtlarını kontrol edin.
12. `/health`: `web=OK`, worker heartbeat `AKTIF`, `healthy=true` bekleyin. İlk görevler henüz tamamlanmamış olabilir. HTTP 200 web erişimini belirtir; worker bozuksa yine 200 ama `healthy=false` olur, dış izleme JSON alanını kontrol etmelidir.
13. Worker loglarında KAP/makro/site/alarm/push sonuçlarını izleyin. ERROR görev bazlı retry/backoff'tur; diğer işler devam eder. Eksik VAPID yalnız push görevini etkiler. Sağlayıcı ağı/rate-limit ve gerçek fiyat tazeliğini staging'de ayrıca kontrol edin.
14. iPhone iOS 16.4+ Safari'de HTTPS alanını açın.
15. Paylaş → **Ana Ekrana Ekle**; uygulamayı Ana Ekran ikonundan açın.
16. Uygulamada **Bildirimleri Aç** düğmesine basın ve izni kabul edin. İzin kullanıcı hareketiyle istenir; iOS tarayıcı sekmesinden push kurulumu desteklenmeyebilir.
17. Hisse detayında kaynak **MANUEL** seçerek fiyat alarmı kurun. Test amacıyla güncel fiyatın gerçekleşmiş tarafında bir eşik kullanabilirsiniz; seans dışında eski fiyata göre tetik beklemeyin.
18. Alarm kontrol periyodu sonrası kartta **TETİKLENDİ**, İstanbul zamanı ve fiyatını kontrol edin. AI alarm hedefi oluşturma snapshot'ından okunur, yeni analizle kaymaz.
19. Push geldiğini ve bildirime dokunmanın doğru hisseyi açtığını kontrol edin. HTTP push kabulü cihazda görünme garantisi değildir; iOS izin/Odak modu/bağlantı etkiler. Belirsiz `SENDING` deliveries otomatik yeniden gönderilmez; PUSH_SETUP.md operasyon notuna bakın.
20. Bilgisayarı kapatın. Uygulama Railway'de çalışır; bu Codex geliştirme ortamı 7/24 production sunucusu değildir.
21. Başka cihazdan worker heartbeat'in ilerlediğini, KAP/site/performance/push işlerinin devam ettiğini doğrulayın; sonraki seans intraday güncellenmesini kontrol edin. Bu gerçek doğrulama yapılmadan 7/24 çalışma kanıtlanmış sayılmaz. 16. adıma geçmeyin.

## Mevcut veriyi koruma / ilk kurulum

Volume `public/`, `private/user-data/`, `runtime/`, `archives/yarin_top10_arsiv/` içerir. Private/runtime HTTP statik servisinin dışındadır; health yalnız güvenli görev alanlarını döndürür. Docker image kullanıcı verileri ve geçmiş piyasa kayıtlarını içermez. Yalnız sektör/şirket referans haritaları ilk boş volume'a üzerine yazmadan kopyalanır.

İlk deploy'dan önce var olan yerel verileri koruyacaksanız **web/worker durdurulmuşken**, güvenilir ortamda `BIST_DATA_DIR=/mutlak/yedek-klasor python veri_yollari.py --migrate` ile düzenlenmiş yedeği oluşturun. Ardından sağlayıcının güvenli volume upload/restore yöntemiyle `/data` içine aktarın; yeni worker'ı ancak aktarım bitince açın. Bu görev gerçek kullanıcı dosyalarını taşımadı. Volume'u silmeyin/recreate etmeyin. Image build/deploy sırasında migration çalıştırılmıyor; mevcut arşiv/user/state üzerine yazılmıyor.

Her kod güncellemesi: kod → inceleme/test → GitHub main push → Railway GitHub autodeploy (Settings/Source'da branch ve autodeploy kontrolü) → eski process'lerin durması → yeni image/process'lerin başlaması. Aynı volume yeniden mount edilir, veriler korunur. Otomatik deploy kapalıysa Deploy/Redeploy elle yapılır. `main`'deki GitHub Actions eski veri tarama cron'unu worker devreye alındığında devre dışı bırakın; iki ayrı üretici ve her data commit'te yeniden deploy döngüsü oluşturmayın.

## Environment listesi

Zorunlu cloud kalıcılığı: `BIST_DATA_DIR` (volume mount). Web: `PORT` (Railway sağlar, yerelde 8000). Push göndermek için üç VAPID değişkeni zorunlu; web bunlar olmadan açılır. `VAPID_SUBJECT` gerçek mailto/HTTPS iletişim adresi. `.env` otomatik yüklenmez; Railway Variables veya shell environment kullanılır.

Tüm diğer ayarlar isteğe bağlıdır; varsayılanlar `.env.example` içinde:

- Periyotlar (sn, 1–86400): `KAP_INTERVAL_SECONDS`, `MACRO_INTERVAL_SECONDS`, `ALARM_INTERVAL_SECONDS`, `PUSH_INTERVAL_SECONDS`, `INTRADAY_TOP10_INTERVAL_SECONDS`, `COMPANY_SITE_INTERVAL_SECONDS`, `FULL_SCAN_INTERVAL_SECONDS`, `PRIORITY_INTERVAL_SECONDS`, `YARIN_TOP10_INTERVAL_SECONDS`, `PERFORMANCE_INTERVAL_SECONDS`, `INTRADAY_PERFORMANCE_INTERVAL_SECONDS`, `MARKET_CONTEXT_INTERVAL_SECONDS`.
- Batch: `FULL_SCAN_BATCH_SIZE` 10 (1–25), `COMPANY_SITE_BATCH_SIZE` 15 (1–20), `COMPANY_SITE_DOMAIN_DELAY_SECONDS` 2, `PERFORMANCE_BATCH_SIZE` 10 (1–25), `GUN_ICI_PERFORMANCE_BATCH_SIZE` 10; dedup `NEWS_DEDUP_WINDOW_SECONDS` 21600.
- Learning: `LEARNING_ENABLED=false`, `GUN_ICI_LEARNING_ENABLED=false`, `MIN_LEARNING_SAMPLES=40`, `GUN_ICI_MIN_LEARNING_SAMPLES=40`, `YARIN_CALIBRATION_MAX_POINTS=3` (0–5).
- Piyasa bağlamı: `MARKET_REGIME_MAX_EFFECT=.75`, `BREADTH_MAX_EFFECT=.75`, `SECTOR_RS_MAX_EFFECT=1` (her biri 0–2), `BREADTH_MIN_COVERAGE=.6`, `BREADTH_MIN_STOCKS=30`, `SECTOR_RS_MIN_STOCKS=5`.
- Yerel alternatifler: `BIST_USER_DATA_DIR`, `BIST_RUNTIME_DIR`. Cloud ortak kökü varken kullanmayın; yalnız aynı alt dizinleri gösterirlerse kabul edilir.
- `BOT_TOKEN`: yalnız Telegram isteyenler için opsiyonel; web/worker/push gerektirmez.

## Health ve sınırlar

Heartbeat ≤30 sn `AKTIF`; 30–120 sn `GECIKMIS`; >120 sn veya STOPPED/missing `DURMUS_OLABILIR`. Görev status/son başarı/başlangıç/retry bilgisi vardır; secrets, endpoint, kullanıcı kimliği yoktur. Heartbeat'in sağlıklı olması her sağlayıcının sağlıklı olduğu anlamına gelmez; görev ERROR/last_success alanlarını da izleyin.

Scheduler açık piyasada döner 10'luk batch kullanır; 805 hisse için agresif startup çağrısı yoktur. Piyasa kapalı intraday/full scan/context atlanır; diğer uygun görevler sürer. Tatil/yarım gün takvimi hâlâ otomatik bağlı değildir. Provider thread'i zorla iptal edilemez; harici çağrıların staging timeout/rate-limit davranışı ve SIGTERM sırasında volume güvenliği gerçek ortamda izlenmelidir. Push mock testleri gerçek Apple/FCM teslimi yerine geçmez.

## Doğrulama

`PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests`

`node tests/test_cloud_ui.cjs` ve mevcut dört `.cjs` test grubu.

`BIST_DATA_DIR=/tmp/gecici-volume python ana_motor.py --check` yalnız offline import/config kontrolüdür. Gerçek deploy ve gerçek VAPID/push teslimi bu görevde yapılmamıştır.
