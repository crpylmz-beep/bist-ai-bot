# Sektör Gücü V1

Mevcut `piyasa_baglami.py` sektör/relatif güç katmanı genişletildi. Eski `build_context`, `stock_context`, `effects` ve yatırım skorları korunur. Yeni gözlemler yalnız API/UI ve gelecekteki frozen metadata içindir; hiçbir TOP10, learning ±3, BASE/LEARNED, Günlük AL/SAT veya Tomorrow Plan formülüne girmez.

## Kaynak ve zaman

İşlem evreni mevcut resmî XUTUM üyelik fonksiyonu/cache'idir. Sektör metadata mevcut `sektor_haritasi.json` dosyasından okunur; metadata crawl veya KAP issuer evreni kullanılmaz. Eşleşmeyen hisseler UNKNOWN; kararlı sektör kimliği gerçek metadata adının SHA256 özetidir. İsimden sektör/endeks kodu tahmin edilmez.

Provider'ın `bp.indices()` kataloğu keşfedilir. İki endeks üyelik isteği/tur; üyelik cache'i yedi gün, katalog en çok64 giriş. Bir endeksin doğrulanmış gerçek üyeleri bir sektörün XUTUM üyelerine **tam eşitse**, o endeks kullanılabilir. Genel XU100/XU050/XU030/XUTUM sektör benchmark'ı değildir. Eşleşmiş endeksler için en çok iki history isteği/tur; kapanmış günün kompakt özeti tekrar kullanılır. Katalog veya endeks hatasında gerçek SOURCE_TRACE + health/backoff korunur; diğer ölçümler kaydedilir. Geniş metadata sektörleri çoğunlukla tam endeks eşleşmesine sahip olmadığından güvenli eşit ağırlıklı sentetik üyeler kullanılır. Kaynak OFFICIAL_INDEX veya SYNTHETIC_MEMBERS olarak görünür.

XU100 mevcut `runtime/market_context_index.json` cache'inden alınır; yeni XU100 veya tüm hisseler için ikinci history taraması yoktur. Eski özetlerde 5/20 seans alanları yoksa **null ve yetersiz veri** gösterilir; sonraki normal analiz/Market Regime yenilemesi yeni alanları üretir. Eski cache'den getiri uydurulmaz.

`teknik_gostergeler.calculate` aynı filtrelenmiş kapanış serisine yalnız return_1d/5d/20d gözlemleri ekler. Günler XIST işlem takvimidir; hafta sonu/tatil atlanır. Eksik bir işlem seansı varsa barlar sıkıştırılmaz, ilgili vade null olur. Açık/future barlar mevcut closed_frame tarafından dışlanır. Ölçüm source asof ve knowledge time en az18:15 olmalıdır. Tüm zamanlar Europe/Istanbul.

## Açıklanabilir ölçüm

- Her vadede relatif güç = sektör getirisi − XU100 getirisi. Sentetik sektör getirisi geçerli üyelerin eşit ağırlıklı ortalamasıdır; her vadede en az5 üye ve sektör üyelerinin en az%60'ı gerekir.
- RS skoru: `50 + sum(weight * clamp(relative/scale,-1,1) * 50)`. 1/5/20 seans ağırlıkları20/35/45%; ölçekler2/5/10 puan. 1G katkısı en çok±10; eksik1G uzun vadelerin ağırlığını artırmaz. 5G veya20G yoksa skor null.
- Trend: üyelerin fiyat/SMA20/SMA50 sıralaması ve20G RS yönü; en az iki üyenin trend ölçümü. Ortalama oy≥0.35 POSITIVE, ≤−0.35 NEGATIVE, diğerleri NEUTRAL.
- Momentum: `RS5/5 − RS20/20` kısa/uzun seans hız farkı, gerçek SMA20 eğimi ve mevcut breadth birlikte değerlendirilir. Momentum ekseni en az iki bileşen ve hız farkı gerektirir. ±0.1 eşikleri; STRONG/IMPROVING/NEUTRAL/WEAKENING/WEAK. Geçmiş breadth değişimi yoksa uydurulmaz.
- Breadth: gerçek kapanış getirisinden yükselen/düşen/değişmeyen. SMA20/SMA50 her biri kendi geçerli üye paydasını kullanır; sample_counts açıkça kaydedilir.
- Hacim: en az5 gerçek hacimli üye ve%60 coverage; yükselen/düşen gerçek hacim payının yönü. STRONG≥60, WEAK<40, diğerleri NORMAL; yetersiz/0 toplam hacim null.
- Sektör durum skoru: RS45%, trend20%, momentum15%, breadth15%, hacim5%; eksik bileşenler normalize edilir. Yeterli5 üye/%60 üye ve horizon coverage, en az3 bileşen, güven≥50 şarttır. ≥80 LEADING, ≥60 STRONG, ≥40 NEUTRAL, ≥20 WEAK, altı LAGGING.
- Güven ayrı: fiyat coverage40%, SMA20/50 coverage20%, hacim coverage15%, vade coverage15%, XU100 kullanılabilirliği10%. Trend/RS çelişkisinde×0.8; yetersiz ölçümde en çok40, eski snapshot'ta0. Güç ile güven karıştırılmaz.
- RRG-benzeri relatif güç/momentum sınıflandırması: RS≥50 ve momentum≥0 LEADING; RS≥50/negatif momentum WEAKENING; RS<50/negatif LAGGING; RS<50/pozitif IMPROVING. Kendi açıklanabilir eksenlerimizdir; lisanslı JdK RS-Ratio/RS-Momentum iddiası yoktur.
- Hisse/sektör RS aynı 1/5/20 seans ölçekleri/ağırlıkları ile hesaplanır. Sektör içi en yüksek/en düşük en çok5 hisse listelenir; AL/SAT önerisi değildir. Hisse+sektör+frozen Market Regime üzerinden uyum metadata'sı üretilir; skor etkisi yoktur.

## Persistence, worker, API

`BIST_DATA_DIR=/data`:

- `/data/public/sector_context.json`: son kompakt gözlem/cache.
- `/data/runtime/sector_context/YYYY-MM-DD.json`: immutable final gözlem.
- `/data/runtime/sector_index_discovery.json`: sınırlı katalog/üyelik/kompakt endeks gözlem cache'i.

Env yoksa mevcut DataPaths public/runtime yerel kökleri kullanılır. Lock+atomic_json; final tarih dosyası asla overwrite edilmez. Ham OHLC serileri kopyalanmaz, eski veriler silinmez. Küçük (<5 üyeli) ve UNKNOWN sektörler açıkça yetersiz kalır; yeterli sektörlerin final kaydını engellemez. Ölçülebilir (≥5 üyeli) bir sektör yetersizse gün final olmaz ve yeni analizleri bekler. Tek sektör kod hatası diğer sonuçları kaydetmeyi engellemez; CODE_ERROR/TASK_ERROR gizlenmez. Partial provider hataları DEGRADED/RETRYING, scheduler diğer görevleri çalıştırır.

Mevcut worker'da `sector_strength` varsayılan300s, `SECTOR_STRENGTH_INTERVAL_SECONDS` ile ayarlanır. Yeni process yok. Açık/kapalı piyasada son kapanmış seans incelenebilir. Aynı final public/archive dosyası tekrar yazılmaz; katalog keşfi bounded cache üzerinden ilerler. `SECTOR_STRENGTH_ENABLED` varsayılantrue, false görev kayıt/çalışma/API'yi kapatır; diğer feature flag'ler bağımsızdır.

GET `/api/sector-strength`, `?sector=<kod veya tam ad>`, `?symbol=<hisse>`; yalnız tek filtre, bilinmeyen/boş/tekrarlı parametre400; yok/bozuk cache503. Hisse detay API'sinde opsiyonel stock_sector_context; eksik cache ana detay yanıtını bozmaz. UI Ana Sayfa'da açılır Sektör Gücü kartı ve bağımsız küçük hisse detay bölümü; Türkçe durumlar, güven/uyarılar,60s görünür sayfa yenilemesi, güvenli metin kaçışı. Tomorrow Plan bölümü korunur.

`frozen_sector_context(doc,symbol,prediction_time)` yalnız metadata hazırlığıdır: final, doğru referans seansı, `as_of≤prediction_time` **ve** hesap bittikten sonraki `created_at≤prediction_time`. Sonradan üretilmiş geriye tarihli bilgi eski prediction'a bağlanamaz. Eski prediction kayıtlarına backfill yok, prediction/result motorları değişmez.

Testler geçici kök, stub provider ve mock HTTP kullanır. Railway/volume/production işlemi yapılmaz.
