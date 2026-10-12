# Sektör Gücü V1

Mevcut `piyasa_baglami.py` sektör/relatif güç katmanı genişletildi. Eski `build_context`, `stock_context`, `effects` ve yatırım skorları korunur. Yeni gözlemler yalnız API/UI ve gelecekteki frozen metadata içindir; hiçbir TOP10, learning ±3, BASE/LEARNED, Günlük AL/SAT veya Tomorrow Plan formülüne girmez.

## Kaynak ve zaman

İşlem evreni mevcut resmî XUTUM üyelik fonksiyonu/cache'idir. Sektör metadata mevcut `sektor_haritasi.json` dosyasından okunur; metadata crawl veya KAP issuer evreni kullanılmaz. Eşleşmeyen hisseler UNKNOWN; kararlı sektör kimliği gerçek metadata adının SHA256 özetidir. İsimden sektör/endeks kodu tahmin edilmez.

Provider'ın `bp.indices()` kataloğu keşfedilir. İki endeks üyelik isteği/tur; üyelik cache'i yedi gün, katalog en çok64 giriş. Bir endeksin doğrulanmış gerçek üyeleri bir sektörün XUTUM üyelerine **tam eşitse**, o endeks kullanılabilir. Genel XU100/XU050/XU030/XUTUM sektör benchmark'ı değildir. Eşleşmiş endeksler için en çok iki history isteği/tur; kapanmış günün kompakt özeti tekrar kullanılır. Katalog veya endeks hatasında gerçek SOURCE_TRACE + health/backoff korunur; diğer ölçümler kaydedilir. Geniş metadata sektörleri çoğunlukla tam endeks eşleşmesine sahip olmadığından güvenli eşit ağırlıklı sentetik üyeler kullanılır. Kaynak OFFICIAL_INDEX veya SYNTHETIC_MEMBERS olarak görünür.

XU100 mevcut `runtime/market_context_index.json` cache'inden alınır. Eksik/eski/horizonsuz cache gerektiğinde aynı provider'ın XU100 history verisiyle bir kez yenilenir; yeterli cache tekrar indirilmez. Market Regime immutable final arşivi değiştirilmez. Eski hisse özetlerinde alanlar yoksa en fazla10 dönen sembol/tur mevcut priority kuyruğuna alınır; normal worker gerçek analizleri kaydeder. Bağımsız/toplu ikinci hisse history taraması veya uydurma getiri yoktur.

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

Env yoksa mevcut DataPaths public/runtime yerel kökleri kullanılır. Lock+atomic_json; final tarih dosyası asla overwrite edilmez. Ham OHLC serileri kopyalanmaz, eski veriler silinmez. Küçük (<5 üyeli) ve UNKNOWN sektörler açıkça yetersiz kalır; yeterli sektörlerin final kaydını engellemez. Ölçülebilir (≥5 üyeli) bir sektör yetersizse gün final olmaz ve yeni analizleri bekler. Tek sektör kod hatası diğer sonuçları kaydetmeyi engellemez; CODE_ERROR/TASK_ERROR gizlenmez. En az bir kullanılabilir sektör ve sağlıklı sentetik fallback varsa optional provider sorunları source_issues, SOURCE_TRACE/SECTOR_TRACE ve worker diagnostics içinde görünür; worker OK_WITH_SKIPS raporlar. Kısmi kullanılabilirlik final snapshot ile karıştırılmaz. Hiçbir kullanılabilir sektör yoksa DEGRADED/RETRYING korunur. Gerçek CODE/STORAGE/CONFIG/UNKNOWN hataları kullanılabilir başka sektör olsa da göreve hata olarak döner. Diğer görevler izole çalışır.

Mevcut worker'da `sector_strength` varsayılan300s, `SECTOR_STRENGTH_INTERVAL_SECONDS` ile ayarlanır. Yeni process yok. Açık/kapalı piyasada son kapanmış seans incelenebilir. Aynı final public/archive dosyası tekrar yazılmaz; katalog keşfi bounded cache üzerinden ilerler. `SECTOR_STRENGTH_ENABLED` varsayılantrue, false görev kayıt/çalışma/API'yi kapatır; diğer feature flag'ler bağımsızdır.

GET `/api/sector-strength`, `?sector=<kod veya tam ad>`, `?symbol=<hisse>`; yalnız tek filtre, bilinmeyen/boş/tekrarlı parametre400; yok/bozuk cache503. Hisse detay API'sinde opsiyonel stock_sector_context; eksik cache ana detay yanıtını bozmaz. UI Ana Sayfa'da açılır Sektör Gücü kartı ve bağımsız küçük hisse detay bölümü; Türkçe durumlar, güven/uyarılar,60s görünür sayfa yenilemesi, güvenli metin kaçışı. Tomorrow Plan bölümü korunur.

`frozen_sector_context(doc,symbol,prediction_time)` yalnız metadata hazırlığıdır: final, doğru referans seansı, `as_of≤prediction_time` **ve** hesap bittikten sonraki `created_at≤prediction_time`. Sonradan üretilmiş geriye tarihli bilgi eski prediction'a bağlanamaz. Eski prediction kayıtlarına backfill yok, prediction/result motorları değişmez.

Testler geçici kök, stub provider ve mock HTTP kullanır. Railway/volume/production işlemi yapılmaz.

## Production bootstrap / PROVIDER_DATA teşhisi

İlk V1 sürümü üç ayrı durumu aynı genel hataya çevirebiliyordu: optional endeks kataloğunda boş/eksik yanıt; eski XU100/hisse özetlerinde 1/5/20 seans alanlarının olmaması; tek eksik sektörden dolayı final olmayan fakat diğer sektörleri kullanılabilir bir rapor. Market Regime final arşivini doğru olarak değiştirmediği için eski XU100 özetinin şema yükseltmesi normal refresh yolunda atlanıyordu. Şema yükseltmesi yalnız kompakt index cache'ine yapılıyor.

`[SECTOR_TRACE]`: failure stage, sektör benchmark kaynakları, valid_sector_count, xutum_member_count, mapped_member_count, usable_history_count, gerçek code ve queued sayısı. MAPPING/BENCHMARK_HISTORY/MEMBER_HISTORY/COVERAGE/SYSTEM_ERROR/PARTIAL_FALLBACK/COMPLETE aşamaları ayrılır. Secret, URL, kullanıcı bilgisi veya ham response loglanmaz. Public source_issues her optional hatanın gerçek code/category/stage/symbol alanlarını tutar.

`runtime/sector_bootstrap_state.json` yalnız son dönen sembol ve enqueue zamanını tutar;300s içinde tekrar enqueue yok. UNKNOWN/eşleşmeyen veya zaten yeterli özetli hisseler enqueue edilmez. Hisse provider hataları normal priority tanı/backoff sisteminde görünür. Gerçek veri gelene kadar null/coverage/uyarılar korunur; bootstrap adına OK veya default veri üretilmez.
