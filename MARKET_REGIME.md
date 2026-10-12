# Piyasa Rejimi + Genişliği V1

Mevcut `piyasa_baglami.py` genişletildi. Eski `piyasa_durumu.json`, ±100 ölçeği, AI/Top10 etkileri, sektör relatif gücü ve `context/annotate/effects` davranışı değiştirilmedi. Yeni 0–100 ölçümler aynı sınıfın `refresh_measurement/measurement` metotlarındadır; mevcut yatırım skorlarına verilmez.

## Kaynak ve kapanış

Resmî `bist_hisseleri_getir` XUTUM listesi günde bir okunur ve kaynak/timestamp ile küçük üyelik cache'i tutulur. KAP/fon/issuer fallback yok. Hisse fiyat çağrısı yapılmaz: mevcut `bist_data.json` içindeki `teknik_gostergeler.closing` özetleri kullanılır. Merkezi teknik yardımcıya yalnız ek kapanış gözlemleri eklendi; mevcut skor bileşenleri aynı kalır. İlk yeni tarama sonrası yeni alanlar birikir. Eksik alanlar null'dır.

Özetin günlük olması, gerçek OHLC/önceki kapanış içermesi, son beklenen XIST seansına ait olması, veri zamanı ve oluşum zamanının gelecekte olmaması gerekir. 18:15'ten önce oluşturulmuş aynı gün özeti final kabul edilmez. Açık mumlar merkezi closed-frame filtresinde çıkarılır. Aynı sembol tek örnektir; çelişkili duplicate dışlanır. Denominator yalnız geçerli üyelerden gelir; coverage ise tüm XUTUM'a göre açıklanır.

XU100 endeksi mevcut borsapy Index sağlayıcısından session başına bir daily6mo çağrısıyla okunabilir; sadece kompakt teknik özet cache'lenir. Hata durumunda hisse breadth sonuçları kaydedilir ve TaskIssue üzerinden provider hatası görünür kalır.

## Hesap

- A/D: kapanış ile önceki kapanış karşılaştırılır; eşitse unchanged. Net A−D, ratio A/D; D=0 ise null.
- Breadth ağırlıkları: advances30%, SMA20 katılım20%, SMA50 katılım20%, high/low dengesi15%, hacim15%.
- Advances=`100×(A+0.5×unchanged)/valid`; SMA metrikleri kendi yeterli örnek paydasını kullanır.
- High/low: son günlük high/low, önceki20 tamamlanmış günlük barın en yüksek/en düşük fiyatını aşarsa yeni yüksek/düşük. Dengesi `50+50×(new_high−new_low)/sample`.
- Gerçek yükselen/düşen işlem hacmi toplam gerçek hacme bölünür; unchanged hacim toplamda kalır. Coverage<60% veya toplam0 ise hacim skor bileşeni dışlanır.
- Eksik bileşenler sıfır değildir; kalan ağırlıklar normalize edilir. Debug'da değer/ağırlık/katkı bulunur.
- State sınırları80/60/40/20: VERY_STRONG/STRONG/NEUTRAL/WEAK/VERY_WEAK; rejim aynı sınırlarla STRONG_BULL/BULL/NEUTRAL/BEAR/STRONG_BEAR.
- Index trend: fiyat>SMA20>SMA50 pozitif; tersi negatif; diğer geçerli yapı nötr.
- Momentum: 3bar getiri, SMA20 eğimi, MACD histogram işareti, RSI45/55 bağlamı; en az2 gerçek bileşenin oy ortalaması ±0.5 sınırı.
- Volatilite: ATR14/fiyat oranının geçmiş60bar medyanına oranı; <0.75 LOW, ≤1.5 NORMAL, ≤2.5 HIGH, üstü EXTREME. Yeterli geçmiş yoksa null.
- Regime ağırlıkları breadth50%, indextrend25%, momentum15%, volatilite10%; eksikler normalize edilir.
- Güven: XUTUM coverage × breadth metrik coverage × index metrik coverage katsayısı; endeks/breadth çelişkisinde×0.75. Yetersiz sayıda en çok35, eski veride0. Skorla karıştırılmaz.
- Sınıf/final için ≥30 geçerli hisse, ≥60% coverage, çok bileşenli breadth/regime ve güven≥50 gerekir. Yetersiz örnekte güçlü rejim etiketi verilmez.
- Risk: extremevol veya breadth<20+declining≥80% EXTREME; yüksekvol/zayıfbreadth/negatifmomentum+declining≥60% HIGH; düşükvol+güçlübreadth+pozitifmomentum LOW; diğer yeterli koşullar NORMAL.

## Kayıt, worker ve API

Public cache `/data/public/market_context.json`; küçük immutable final snapshot `/data/runtime/market_context/YYYY-MM-DD.json`; membership/index küçük cache'leri runtime altında. Yerelde mevcut public/runtime kökleri kullanılır. Lock+atomic yazım; final dosya varsa yeniden hesapla/overwrite yapılmaz. Aynı günlük ham veriler/history kopyalanmaz, kalıcı geçmiş silinmez. Kapalı piyasada değişmeyen public özet yeniden yazılmaz.

İzole `market_regime` scheduler görevi300s, `MARKET_REGIME_INTERVAL_SECONDS` mevcut interval sistemiyle ayarlanabilir. Kapalı piyasada da son kapanış kaydı tamamlanabilir; yeni process veya tüm XUTUM fiyat taraması yok. Eski `market_context` görevi korunur. `MARKET_REGIME_ENABLED` varsayılan true; false yeni görevi/API'yi kapatır, eski motorlar çalışır. Hatalar scheduler backoff/health sınıflandırmasına gider.

Mevcut `/api/market-context` genişletildi: legacy alanlar + yeni gözlem alanları. Ölçüm cache'i yok/bozuksa503; flagfalse enabled=false. UI açıkça sınırlı/eski veriyi gösterir. Backend XIST/market_open kullanır. Dashboard kartı Türkçe; açılır bölüm gerçek bileşen/neden/uyarıları gösterir. XSS metin kaçışı ve mevcut60s görünür sayfa yenilemesi kullanılır.

## Prediction hazırlığı

`frozen_market_context(doc,prediction_time)` yalnız metadata döndürür. `as_of≤prediction_time` yanında hesap tamamlandıktan sonra kaydedilen gerçek `created_at≤prediction_time`, final ve doğru referans seansı şarttır. Sonradan oluşturulmuş geçmiş-tarihli özet eski tahmine bağlanamaz. Bu görevde prediction memory'ye otomatik alan eklenmedi/backfill yapılmadı; eski kayıtlar ve skorlar korunur. Rejim bazlı otomatik öğrenme yoktur.

Testler geçici kökler ve mock provider/HTTP kullanır. Railway/gerçek production kontrolü yapılmaz.

Worker SIGTERM regresyon testinin hazırlık beklemesi paylaşılan CI CPU koşulları için15s oldu; gerçek kapanış sınırı3s ve üretim worker davranışı değişmedi.
