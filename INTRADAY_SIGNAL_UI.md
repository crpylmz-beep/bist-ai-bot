# Günlük AL/SAT ekranı V1

Mevcut tek HTML/CSS/JavaScript PWA içinde alt navigasyondaki Günlük AL/SAT düğmesi bağımsız sayfayı açar. Yeni frontend veya grafik bağımlılığı yoktur.

- `/api/intraday-signals?limit=1000`: backend sırası korunur; AL/SAT/İzle ve güven/teknik/teyit filtreleri yalnız görüntülemeyi etkiler. Market durumu backend `market_open` alanıdır; saatten tahmin edilmez. Bu geriye uyumlu alan boş listelerde de döner.
- Kartlar gerçek son fiyat, teknik güç, güven, teyit, yaşam döngüsü, yaş, İstanbul güncelleme saati, veri kalitesi, likidite ve uzama riskini gösterir. AL seviyeleri yalnız kayıttan okunur; SAT/İzle için AL seviyeleri gösterilmez.
- Teknik detaylar yerleşik `details` ile açılır. Reasons/warnings mevcut `yarinMetin` HTML kaçışından geçirilir. Hisse kodları da attribute dahil kaçış uygulanarak ve event listener ile bağlanır.
- Hisse detayı mevcut `hisseDetay` ve `/api/stocks/{symbol}` içindeki `intraday_signal` alanını kullanır; hesaplama yapılmaz. Geri düğmesi Günlük AL/SAT ekranına döner.
- `/api/intraday-signal-performance?period=all_time&horizon=...`: 30m/60m/120m/SEANS/D1/D3. API grupları sinyal yaşam döngüsüne göre ayrı gösterilir; farklı grupların oranları ortalanmaz. Doğrulanmış `sample_size` 30 ve backend `sufficient` koşulu olmadan başarı oranı gösterilmez. Güvenilirlik 30/100/300 sınırları korunur; tamamlanan, MFE/MAE, hedef/stop yalnız API çıktısıdır.
- Sayfa açıkken 60 saniyede yenileme; document.hidden iken ağ çağrısı yapılmaz. Tekrar görünür olduğunda yenilenir. Başka sayfaya geçiş timer'ı temizler.
- Kapalı seans ve eski veri canlı aday olarak gösterilmez; backend dönüştürmesi korunur. Loading, empty, error ve feature-disabled durumları ayrı metinlerle gösterilir.
- Mevcut 100dvh, safe-area ve içerik scroll sistemi korunur. 6 sütunlu navigasyon ve mobile-first kartlar; masaüstünde iki kolon. Yerleşik button/select/details/progress, yazılı sinyal etiketleri ve ARIA tab/tabpanel kullanılır.

Test: `node tests/test_intraday_signal_ui.cjs` (VM assertions + mock HTTP Chromium 430×932 ve 1280×900). Gerçek production/PWA cihaz doğrulaması bu görevde yapılmaz.

Sinyal ve performans formülleri, kapanmış 5m veri kuralları, TOP10/BASE/LEARNED, tahmin hafızası ve kalıcı kayıtlar değiştirilmez.
