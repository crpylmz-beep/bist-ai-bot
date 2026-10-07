# Bağımsız Günlük AL/SAT V1

Motor `gunluk_al_sat.py` içinde, model `GUNLUK_AL_SAT_V1` olarak ayrıdır.
Yarın TOP10, Gün İçi TOP10, eski sinyaller ve orta/uzun vadeli seviyeler
yeniden hesaplanmaz veya değiştirilmez. Öğrenme ağırlığı uygulanmaz.

## Etkinleştirme ve zamanlama

`INTRADAY_SIGNAL_ENGINE_ENABLED=true` worker başlangıcında yeni
`intraday_signals` görevini kaydeder. Varsayılan **true**: ortam değişkeni
yoksa motor devrededir. Açık `false` ayarında veri çekilmez veya yeni geçmiş
yazılmaz; eski davranış korunur. Ortam değişikliği
sonrasında worker yeniden başlatılır. Görev mevcut scheduler, technical lane,
single-flight, hata sınıflandırması ve backoff sistemini kullanır.

Başlangıçta bir kez `[INTRADAY_SIGNAL] enabled=true timeframe=5m market_gate=enabled`
veya `[INTRADAY_SIGNAL] enabled=false` loglanır. Açık flag ile piyasa kapalıysa
`[INTRADAY_SIGNAL] market_closed skip` en fazla görev periyodunda bir kez
loglanır; her worker tick'inde tekrar edilmez.

Varsayılan periyot 300 saniyedir. `INTRADAY_SIGNALS_INTERVAL_SECONDS=600`
ile on dakikaya çıkarılabilir; 300 saniyeden daha agresif ayar reddedilir.
Mevcut XIST/piyasa-açık kontrolü kullanılır. Piyasa kapalıyken tarama yoktur.

## Gerçek veri ve iki aşamalı tarama

Timeframe 5m; mevcut TradingView/borsapy altyapısı kullanılır. Mevcut stream
sonuçları opsiyonel, salt okunur bir tüketiciye aktarılır. En fazla 2000 sembol
ve sembol başına 300 mum RAM'de tutulur; ikinci disk OHLCV cache'i yoktur.

Resmî `bist_hisseleri_getir()` XUTUM pay evreni kullanılır; KAP issuer evreni
kullanılmaz. Cache'teki gerçek kapalı mumlar hızlı momentum ön taramasına
girer. Tur başına en fazla 30 detaylı analiz yapılır: 10 dönen evren sembolü
öncelikli, kalan yerler hızlı adaylara ayrılır. Böylece adaylar hızlı yenilenir,
diğer semboller de zamanla incelenir. Her hisseye beş dakikada bir detaylı
analiz garantisi yoktur; coverage/candidate/processed sayıları raporlanır.

Eksik/eski cache için sadece bu sınırlı batch'te mevcut `Ticker.history`
`period=1d, interval=5m` çağrılır. Unsupported semboller mevcut ortak
`provider_unsupported.json` indeksine açık gerekçeyle kaydedilir ve altı saat
yeniden denenmez. Diğer hatalar loglanır; başarılı hisseler kaydedildikten sonra
worker görevi gerçek hata bilgisiyle DEGRADED/ERROR olarak raporlanabilir.

## Karar ve seviyeler

Ortak `teknik_gostergeler` closed-frame, VWAP, EMA, RSI, MACD, OBV,
Bollinger ve momentum fonksiyonları kullanılır. ATR aynı gerçek 5m OHLCV'den
14 mumluk true range ortalamasıdır. Günlük veriden intraday değer üretilmez.
Kapalı mum zamanı, OHLC tutarlılığı, seans içi 5dk aralıkları, en az 35 mum
ve en fazla 10 dakikalık veri yaşı denetlenir.

Dokuz kriter: VWAP, EMA, RSI, MACD/histogram, hacim, OBV, Bollinger,
momentum, mum yapısı. Her kriter AL/SAT/NEUTRAL/MISSING verir. Eksik veri
teyit sayılmaz. AL/SAT için en az altı teyit, üç ayrı aile, 60 güven ve iyi
likidite gerekir. RSI aşırı bölge tek başına AL/SAT üretmez.

Technical score = baskın tarafın teyit sayısı / 9 ×100.
Confidence = veri kapsaması × teyit oranı × karşı teyit uyumu ×100;
likidite, aşırı uzama ve AL için kötü/eksik risk-getiri bunu azaltır.
Teyit düzeyi: 0–3 ZAYIF, 4–5 ORTA, 6–7 GUCLU, 8–9 COK_GUCLU.
Minimum son mum işlem tutarı 100.000 TL; hacim teyidi önceki 20 mumun
ortalamasının %130'udur. Bunlar V1 merkezi sabitlerdir, öğrenilmiş ağırlık değildir.

AL bölgesi fiyat/VWAP/yakın destek ve ATR ile sınırlanır. Stop destek altı
ATR tamponudur; hedef direnç veya ATR projeksiyonudur. Destek/direnç
hesaplarında sinyal mumundan önceki mumlar kullanılır. Eksik/geçersiz yapı
null + reason üretir. R/R = (hedef−giriş)/(giriş−stop); düşük R/R AL güvenini
azaltır. Bu seviyeler eski hisse analizindeki AL/HEDEF/STOP alanlarına yazılmaz.

Kırılım: önceki 20 mumun direnci geçilmediyse WAITING; geçildi fakat hacim
%130 altında/eksikse WEAK_CONFIRMATION; geçildi ve hacim teyitliyse CONFIRMED.
Mum yönü, kapanış konumu, yüksek/düşüğe yakınlık ve basit bullish engulfing
açıklanır. Fiyat VWAP'tan üç ATR'den fazla uzaklaştığında sınırlı uzama cezası
uygulanır; kör yükseliş/düşüş takibi engellenir.

## Yaşam döngüsü ve veri güvenliği

YENI_AL/AL_DEVAM/ZAYIFLIYOR/SAT_DONUS/YENI_SAT/SAT_DEVAM/
TOPARLANIYOR/IZLE, önceki aktif yön ve yeni karardan deterministik çıkarılır.
Başlangıç zamanı ve yaş İstanbul saatindedir. Aynı mum tekrarında yeni
transition yoktur. Yeni seansta yön başlangıcı sıfırlanır; gelecek tarihli eski
state kullanılmaz.

`/data/runtime/gunluk_al_sat_state.json`: son durum ve dönen batch cursor'u.
`/data/runtime/gunluk_al_sat_gecmisi/YYYY-MM-DD.json`: anlamlı frozen events.
`/data/public/gunluk_al_sat.json`: güncel API cache'i.
Yerelde mevcut merkezi runtime/public yolları kullanılır.

Geçmişte IZLE spam'i tutulmaz. Yön/durum geçişleri ve devam sinyalindeki en az
10 puanlık önemli teknik değişimler kaydedilir. Symbol + kapalı mum zamanı +
state kimliği duplicate'ı engeller. Lock + atomic write kullanılır; var olan
event değiştirilmez. Geçmiş önce, state sonra yazılır; restart tekrarında aynı
event iki kez oluşmaz. Frozen events analysis_only olarak saklanır; bu görev
1–3 günlük sonuç motorunu veya otomatik öğrenmeyi devreye almaz.

## API

`GET /api/intraday-signals?signal=AL&limit=100&min_confidence=60`

- signal: AL/SAT/IZLE; yoksa tüm gruplar.
- limit: 1–1000; min_confidence: 0–100.
- Geçersiz/tekrarlanan parametre 400; bozuk/eksik cache 503.
- Flag kapalıysa enabled=false ve boş gruplar.
- Eski veya piyasa kapalı veri live_signal=false, signal=IZLE;
  eski sinyal recorded_signal alanında korunur.
- `/api/stocks/{symbol}` yanıtına flag açıkken opsiyonel `intraday_signal`
  eklenir. Eski otomatik/manüel alanlar ve alarm contract'ı değişmez.

Tam alarm UI'si, yeni push, otomatik ağırlık değişimi veya yeni sağlayıcı yoktur.
Her sembol hatası izole edilir; stream-cache tüketicisi hatası eski taramaya
yayılmaz. API cache'i geçmiş dosyalarını taramaz. Kalıcı veriler silinmez.
