# Deployment hazırlığı doğrulama raporu

Gerçek Railway deploy yapılmadı. İki ayrı Railway servisinin tek volume paylaşımı mevcut sağlayıcı modeliyle mümkün değildir. Dosya mimarisi korunarak bir Railway serviste iki ayrı process için kurulum hazırlandı. İki servis şartı için ortak veri deposu dönüşümü gereklidir. Docker build bu ortamda paket indirirken DNS hatası verdi; production image build doğrulanmış değildir.

## Bu görevde değişen / eklenen dosyalar

- Başlatma/build: `Procfile`, `Dockerfile`, `.dockerignore`, `.python-version`, `railway.toml`, `cloud_baslat.py`, `requirements.txt`.
- Sunucu/worker: `web_server.py`, `ana_motor.py`, `ana_motor_gorevleri.py`.
- UI: `webapp/index.html`.
- Secret hazırlığı: `vapid_uret.py`, `.env.example`, `.gitignore`.
- Testler: `tests/test_cloud_readiness.py`, `tests/test_cloud_ui.cjs`, güncellenen `tests/test_ana_motor.py`.
- Belgeler: `RAILWAY_DEPLOY.md`, `README.md`, `ANA_MOTOR_SETUP.md`, `DATA_PERSISTENCE.md`, bu rapor.

Önceki adımların mevcut değişiklikleri korundu. Teknik seçim/puanlama algoritması, immutable arşivler, learning flag'leri veya gerçek kullanıcı verisi değiştirilmedi. Gerçek volume migration ve Git commit/push yapılmadı.

## Denetim ve davranış

Web `0.0.0.0:$PORT`; worker bağımsız `ana_motor.py`. Supervisor web restart'ında worker'ı durdurmaz; worker crash'ında deployment'ın yeniden başlatılması için nonzero exit verir. Shutdown her iki child'a SIGTERM iletir; tamamlanmayan provider için 25 sn üst sınır vardır.

`BIST_DATA_DIR` altında `public`, `private/user-data`, `runtime`, `archives` ayrımı korunur. Dosya atomik yazım/flock kullanımı mevcut modüllerden gelir. Image içine kullanıcı verileri, runtime ve piyasa geçmişi alınmaz; yalnız iki referans haritası kopyalanır. İlk boot seed işlemi mevcut referans haritasını overwrite etmez.

`/health` doğru volume runtime'ını okur; web OK, worker AKTIF/GECIKMIS/DURMUS_OLABILIR, heartbeat yaş/zamanı ve görevlerin son başarı/başlangıç/retry bilgilerini döndürür. Runtime'ın diğer alanları aktarılmaz. HTTP 200 web liveness içindir, worker readiness JSON `healthy` alanındadır.

Provider hatalarında mevcut görev izolasyonu/backoff korunur. Alarm adapter'ı piyasa kapalıysa provider okumaz; KAP, makro, şirket sitesi, performans, push sürer. Döner batch başlangıcı korunur. Resmi tatil/yarım gün takvimi henüz bağlı değildir.

Service worker mevcut dosyadır; yenisi yaratılmadı. Scope `/`, notificationclick same-origin hisse detayına gider. HTML, JSON, manifest ve service worker için no-store HTTP başlıkları eklendi. iOS 16.4+ Ana Ekran PWA ve gerçek HTTPS gerekir.

UI'da ortak AI karar/puan/confidence, gerekçe, haber/KAP/makro/sektör katkıları ve piyasa rejimi/breadth/sektör RS mevcut backend alanlarından gösterilir. Günlük ve intraday ayrı seviyeler, manuel seviyeler ve alarm türleri korunur. Ana sayfada worker heartbeat durumu görünür. Ana sayfanın sahte “ekrana yüklenme saati” yerine JSON timestamp/veri yaşı gösterilir. Aktif ana/TOP10/haber ekranları 60 sn yenilenir, arka plan sekmede polling durur. Detay mevcut 30 sn yenilemesinde AI özet ve seviyeler güncellenir; manuel taslaklar ezilmez. Yarın frozen/canlı/performance, intraday stale, KAP+ŞİRKET_SITE kaynakları mevcut kartlarında kalır.

## Test sonuçları

- **312 Python unittest: OK**, mevcut tam suite dahil. Mock provider/push ve geçici klasörler; gerçek kullanıcı dosyası yok.
- **5 JavaScript smoke grubu: OK**: cloud UI görünürlük/escaping/tazelik, push/SW/click, manuel seviyeler/alarm, Yarın kartları, canonical haber kaynakları.
- Python syntax, Railway TOML parse ve `ana_motor.py --check` imports: OK; geçici volume ve BOT_TOKEN/VAPID olmadan.
- HTTP testleri: PORT env, 0.0.0.0, custom volume health, HTML/SW/manifest/no-store, missing VAPID, özel HTTP dosya engelleri: OK.
- Supervisor mock testleri: web restart worker'ı koruyor; worker crash nonzero/cleanup: OK.
- Önceki suite: restart state/kuyruk/dedup, immutable snapshot, alarm/subscription kullanıcı izolasyonu, provider error/backoff ve performans/lookahead testleri: OK.
- VAPID anahtar çifti py-vapid ile doğrulandı; private file 0600, ikinci üretim overwrite reddedildi.
- `.env`, `.local`, `.pem`, `.key` ignore kontrolü: OK; bu dosyaların tracked secret örneği yok. `git diff --check`: OK.
- **Docker build tamamlanamadı:** container build ağı paket indeksini çözemedi (Temporary failure in name resolution); normal ve host network denemesi aynı nedenle başarısız. Kod testleri production Docker image build'inin yerine geçmez.

## Gerçek 7/24 için son işler

Kullanıcı tarafında GitHub push; Railway build; bir serviste web+worker ve kalıcı volume (veya iki servis isteniyorsa ayrı veri deposu çalışması); mevcut veri güvenli restore; VAPID secret; HTTPS domain; eski Actions cron'unu devre dışı bırakma; health/log/provider staging kontrolü; iPhone alarm+push tıklama; bilgisayar kapalıyken heartbeat ve sonraki seans güncelleme kanıtı. Tam sıralı adımlar RAILWAY_DEPLOY.md'dedir. Bu doğrulama tamamlanmadan 16. adıma geçilmez.

## Eksik main dosyalarının tamamlanması

Cloud başlatıcı ve önceden hazırlanmış bağımlı çalışma kodu main için ayrı temiz checkout üzerinde toplandı. Yeni başlatıcı log/PID, environment aktarımı, bounded shutdown ve gerçek SIGTERM/SIGINT testleri eklendi. Aday main üzerinde 325 Python testi ve 5 JavaScript grubu geçti. Private/generated/runtime JSON gönderilmedi. VAPID üretici artık değerleri yalnız terminalde gösterir, anahtar dosyası oluşturmaz. Gerçek Railway deployment durumu ayrıca Logs ve /health ile doğrulanmalıdır.
