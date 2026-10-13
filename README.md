# BIST Asistanı

Yerelde bağımlılıklar: `python -m pip install -r requirements.txt` (Python 3.13).

Web: `python web_server.py`; bağımsız worker: `python ana_motor.py`.

Railway kalıcı volume ve HTTPS/PWA kurulumu: [RAILWAY_DEPLOY.md](RAILWAY_DEPLOY.md).
Railway tek volume'u iki servise paylaşmaz; hazırlanmış kurulum bir serviste iki ayrı process kullanır. İki ayrı servis için ortak veri deposuna geçiş gerekir.

Veri yolu/migration: [DATA_PERSISTENCE.md](DATA_PERSISTENCE.md). Worker: [ANA_MOTOR_SETUP.md](ANA_MOTOR_SETUP.md). Push: [PUSH_SETUP.md](PUSH_SETUP.md).

Testler: `python -m unittest discover -s tests`; JavaScript smoke testleri `tests/*.cjs`.

Pozitif kapanış havuzu, Yarın TOP10/30/50 ve 1/3/5 günlük ölçüm: [POZITIF_KAPANIS.md](POZITIF_KAPANIS.md).

V6 PostgreSQL/R2 hazırlığı ve kaynakları silmeyen DRY_RUN taşıma: [docs/STORAGE_V6.md](docs/STORAGE_V6.md). Varsayılan `STORAGE_BACKEND=legacy`; gerçek bağlantı ve production geçişi otomatik yapılmaz. Kapasite/maliyet sınırları: [docs/STORAGE_V6_COSTS.md](docs/STORAGE_V6_COSTS.md).

Merkezi pay fiyatları `borsa_fiyat_motoru.py` tarafından mevcut worker içinde, varsayılan 60 saniyelik `quote_refresh` göreviyle yayımlanır. KAP doğrulanmış pay listesi kullanılır; başlangıç abonelikleri tur başına 100 ile sınırlıdır. `borsa_fiyatlari.json` yalnız son doğrulanmış durumu tutar; tahmin arşivi veya öğrenme geçmişini değiştirmez. Günlük yüzde aynı sağlayıcının son fiyatı ve önceki seans kapanışından hesaplanır. Eksik referans için yüzde gösterilmez; eski fiyat zaman etiketiyle korunur. Anonim borsapy/TradingView akışı yaklaşık 15 dakika gecikebilir; 60 saniyelik ekran yenilemesi gerçek zaman garantisi değildir. Mevcut lisanslı erişim varsa `BIST_TRADINGVIEW_AUTH_TOKEN` güvenli ortam değişkeninden okunur; erişim koşulları aşılmaz. Oracle güncellemesi mevcut repo dizininde: `git fetch origin main && bash <(git show origin/main:tools/oracle_price_update.sh)`. Betik yerel değişiklik veya tanımlanamayan servis durumunda durur; veri/DB/ortam ayarlarını değiştirmez.
