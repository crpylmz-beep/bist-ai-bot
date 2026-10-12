# Günlük AL/SAT gerçek performans V1

Mevcut `GunIciPerformans.signal_round()` yeni frozen sinyal türünü değerlendirir.
Yeni sağlayıcı, scheduler veya ikinci performans motoru yoktur. Mevcut
`intraday_performance` worker görevi önce eski Gün İçi TOP10 performansını,
ardından bu adapter'ı çalıştırır. Eski TOP10 geçmişi ve öğrenme girdileri
birleştirilmez. Yeni `intraday_sinyal_performansi.py` yalnız outcome, kalite,
istatistik, clean dataset ve API yardımcıları içerir.

## Sinyal ve snapshot

Kaynak `/data/runtime/gunluk_al_sat_gecmisi/YYYY-MM-DD.json` dosyalarıdır.
Yeni olaylarda `prediction_price`, `engine_version`, `snapshot_version` ayrıca
dondurulur. Eski geçerli V1 olaylarının donmuş `price`/`model` alanları eşdeğer
okuma alias'ıdır; eski dosyaya alan eklenmez. İndikatör veya eksik seviye
bugünkü analizden tamamlanmaz. Kaynak hash'i sonuca bağlanır; kaynak değişirse
eski sonuçla birlikte clean dataset'e alınmaz.

YENI_AL, YENI_SAT, SAT_DONUS ve AL_ADAYI içeren TOPARLANIYOR takip edilir.
TOPARLANIYOR + IZLE yalnız bağlamdır; yeni AL tahmini değildir. ZAYIFLIYOR
ayrı dışlama kategorisidir. AL_DEVAM/SAT_DEVAM için önceki frozen olayla en az
10 puan teknik veya güven değişimi gerekir. Persistence da yalnız bu anlamlı
devam olaylarını kaydeder; skor/güven formülü veya eşikleri değiştirilmez.

## Ufuklar ve fiyat

Ufuklar: `30m`, `60m`, `120m`, `SEANS`, `D1`, `D3`.
Sinyal zamanından önce başlayan mumlar kullanılmaz. Sinyal rastgele saniyede
oluşmuşsa ilk tam sonraki 5dk mum başlangıcına geçilir. Açık/future, eksik,
çakışan veya geçersiz OHLC kullanılmaz. Her ufuk kendi son zamanı ile
normalizasyonu sınırlar; sonraki ufuk verisi erken sonuca geri sızmaz.

30/60/120 dakika seans sonuna sığmıyorsa kısaltılıp tamamlandı sayılmaz:
`PENDING / HORIZON_EXCEEDS_SESSION` kalır. SEANS ayrı 18:10 ufkudur.
D1/D3 mevcut XIST işlem günlerini kullanır. MFE/MAE sinyal seansının sadece
sinyalden sonraki 5dk bölümünü ve sonraki işlem günlerinin gerçek günlük
OHLC'sini kapsar. Sinyal gününün tam günlük OHLC'si kullanılmaz.

5dk fiyatı mevcut `GunIciPerformans.prices()` ve ortak 7 günlük mum cache'inden
gelir. D1/D3 mevcut merkezi günlük fiyat cache'i veya `provider_history` ile
aynı borsapy provider'dan alınır. Yeni disk OHLCV cache'i oluşturulmaz.
Tur başına en fazla 10 sembol, sembol başına en fazla 50 olay; fiyat her sembol
için bir kez okunur. Dönen cursor ve retry, eksik kayıtların sırayı kilitlemesini
önler. Eski eksik fiyatlar tamamlandı diye işaretlenmez veya silinmez.

AL direction return = (future / prediction − 1) ×100.
SAT direction return = (prediction / future − 1) ×100.
SAT_DONUS SAT'tır. SAT MFE düşüşten, MAE yükselişten aynı ters oranla ölçülür.
Bu betimleyici yön ölçümüdür; eski merkezi motorun getiri formülü değiştirilmez.

## Temaslar ve alım bölgesi

Yalnız frozen, yönü doğru hedef/stop kullanılır; SAT için AL seviyeleri
aynalanıp uydurulmaz. Eksik/geçersiz seviyede hit bilgisi null kalır.
İlk temas TARGET_HIT/STOP_HIT/NEITHER/AMBIGUOUS olarak görünür. Aynı 5dk mumda
iki seviye görülmüşse ilk temas sırası uydurulmaz. Günlük OHLC'deki aynı gün
çift teması da AMBIGUOUS'tur; sonuç çözünürlüğü açıkça gösterilir.
AMBIGUOUS başarı oranı ve clean dataset dışında kalır.

Buy-zone giriş, ilk OHLC aralık kesişimiyle bulunur; timestamp mumun zamanıdır,
kesin intrabar dolum zamanı değildir. Giriş mumunun yüksek/düşüğü girişten önce
olabileceği için post-entry MFE/MAE sadece sonraki tamamlanmış mumlarla ölçülür.
Referans her zaman frozen prediction price'dır; tahmini dolum fiyatı üretilmez.

## Analiz ve güven

Signal/state; teknik ve güven bucket'ları 0–49/50–59/60–69/70–79/80–89/90–100;
gerçek count/total teyit grupları raporlanır. İndikatörler yalnız frozen ham
alan ve teyit mevcutsa ölçülür. Eksik veri MISSING kalır; kriter olumlu sayılmaz.
VWAP, EMA, RSI/bucket, MACD/histogram, hacim, OBV, Bollinger, ATR/volatilite,
momentum, mum, breakout, uzama cezası ve R/R desteklenir.

Yedi sabit combo: VWAP+EMA, VWAP+hacim, EMA+MACD, MACD+hacim,
VWAP+EMA+hacim, VWAP+EMA+MACD, VWAP+EMA+MACD+hacim.
Tüm bileşenlerin frozen ham alanı ve teyidi gereklidir.

7d/30d/90d/all_time, sinyal zamanına göre kohort seçer; ufuklar ayrıdır.
Ortak `sinyal_performansi.Stats` ve merkezi 30/100/300 güven eşikleri kullanılır.
Az örnek INSUFFICIENT'tır. Success yalnız doğrulanmış pozitif direction return;
sıfır nötrdür. Pending/ambiguity/unverified/future/bad price/OHLC/duplicate
conflict/source-hash conflict öğrenme örneği değildir. `clean_dataset()` frozen
feature ve doğrulanmış etiketi ayırır; otomatik ağırlık güncellemesi yoktur.

## Persistence ve API

`/data/runtime/intraday_signal_results/YYYY-MM-DD.json`: kaynak hash'i ve
ayrı outcome'lar; completed sonuç tekrar yazılmaz.
`/data/runtime/intraday_signal_performance_state.json`: cursor.
`/data/public/intraday_signal_performance.json`: türetilmiş API cache'i.
Yerelde merkezi yol fallback'leri kullanılır. Lock + atomic write; önceki sağlam
cache başarısız yazımda korunur. Frozen kaynaklar ve prediction memory değişmez.
Bozuk tek kayıt dışlanır; diğer kayıtlar devam eder. Provider/disk hatası mevcut
worker hata sınıflandırması/backoff'una gider; diğer görevler çalışır.

`GET /api/intraday-signal-performance`

Filtreler: signal=AL/SAT/IZLE; state; horizon (varsayılan 60m); period
(varsayılan all_time); indicator; condition. min_confidence desteklenen
merkezi kesitler: **0,50,60,70,80,90,100**. Diğer değerler 400'dür; API geçmiş
taramaz. Her kesitin istatistikleri önceden hesaplanır; hesaplama sırasında
kesitler sırayla işlenerek örnek dizilerinin RAM'de çoğalması önlenir.
Geçersiz/tekrarlanan filtre 400; eksik/bozuk cache 503. Yanıt `groups` içinde
summary, skor/güven/teyit ve indikatör istatistiklerini içerir.

Flag varsayılan true, mevcut 5m signal formülleri, TOP10, BASE/LEARNED,
öğrenme ±3 sınırı, XUTUM ve şirket sitesi izolasyonu değiştirilmez.
Railway doğrulaması bu geliştirme görevinin kapsamında değildir.
