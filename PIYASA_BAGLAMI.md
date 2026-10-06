# BIST piyasa bağlamı

`piyasa_baglami.py` tek bir ortak piyasa bağlamı üretir. Mevcut BIST100 verisi, hazır günlük/Gün İçi analizleri ve `sektor_haritasi.py` haritasını kullanır; yeni fiyat provider'ı veya ikinci sektör haritası yoktur. Ortak AI'daki tek günlük yüzde değişim proxy'si, üretilmiş bağlamla değiştirilir. Eski doğrudan API çağrılarının sayısal rejim girdisi geriye uyumlu okunur; normal ortak AI batch'i yeni bağlam eksikse BELIRSIZ döner.

## Kapsama ve tazelik

Breadth ve sektör hesabı aday TOP10'dan değil, izlenen evrenden yapılır. Gün İçi Stream'deki kapanmış mumlar, teknik filtreden elenen hisseler dahil yeniden kullanılır; gösterge hesapları tekrarlanmaz. Günlük batch mevcut `bist_data.json` verisini birleştirir. Günlük getiri önceki kapanışa, Gün İçi getiri mevcut analizdeki ilk seans mumunun açılışına göredir; `getiri_bazi` bunları ayırır. Endeks karşılaştırması aynı bazda yapılır.

Varsayılan minimum kapsama %60 (`BREADTH_MIN_COVERAGE`, 0.5–1), minimum geçerli hisse 30 (`BREADTH_MIN_STOCKS`, 30–1000). Fiyat/getiri/zamanı olmayan, gelecekteki, başka seans gününe ait veya 20 dakikadan eski gözlemler dışlanır. 10–20 dakika yaş confidence'ı azaltır. Kapsama yetersizse breadth score bilinmeyen ve rejim BELIRSIZ olur; yükselen/düşen sayıları yalnız gözlenen kümenin sayılarıdır.

Hisse zamanları ayrı tutulur: eski batch satırları yeni dosya yazıldığı için tazelenmez. Rapor yaşı ile hesaplama anındaki fiyat yaşı birlikte değerlendirilir; rapor yeni olsa bile input yaşı 20 dakikayı aşınca etki durur. BIST100'ün kendi `updated_at` alanı vardır. Mevcut endeks sorgusu başarılıysa 5 dakika boyunca tekrar kullanılabilir; hata halinde eski değer eski timestamp'iyle kalır. Piyasa bağlamı hiçbir provider çağrısı yapmaz. Zamanı olmayan eski endeks rejime doğrulanmış katkı yapmaz.

## Breadth

Getiri >%0.01 yükselen, <%−0.01 düşen; aradaki değer değişmeyen sayılır. Güçlü hareket eşiği ±%3, hacim desteği hazır hacim oranında ≥120'dir. Yükselen/düşen oranı, pozitif/negatif yüzde, güçlü ve hacim destekli sayı ayrı çıkarılır. Düşen yoksa oran sonsuz gibi JSON dışı değer yerine null'dır.

`breadth_score = 100 × (yükselen − düşen) / geçerli_hisse`. Sınıflar COK_POZITIF/POZITIF/NOTR/NEGATIF/COK_NEGATIF; eşikler ±55 ve ±20. Kapsama eşiği geçilmeden score uygulanmaz. Eksik hacim yükselen/düşen fiyat sayımını engellemez, hacim desteği uydurulmaz.

## Sektör relatif güç

Mevcut harita salt okunur; dosya yoksa otomatik 805 şirket sorgusu başlatılmaz. BILINMIYOR ayrı tutulur. Her sektörde en az 5 geçerli hisse (`SECTOR_RS_MIN_STOCKS`, 5–100) ve kendi izlenen sektör evreninin en az kapsama eşiği gerekir; genel breadth de yeterli olmalıdır.

Piyasa referansı taze BIST100 getirisi, yoksa yeterli izlenen evrenin medyan getirisidir. Referansın türü kaydedilir. `relatif_getiri = sektör_medyan_getiri − piyasa_getirisi`; `rs_score = clamp(relatif_getiri × 25, −100, 100)`. Medyan tek uç hisseye karşı korunur; ortalama ayrıca raporlanır. Sınıflar COK_GUCLU/GUCLU/NOTR/ZAYIF/COK_ZAYIF, eşikler ±50 ve ±15.

Hisse sayısı, pozitif oran, ortalama/medyan, hazır hacim desteği, mevcut MA/EMA üstündeki hisse dağılımından trend skoru, RS ve confidence ayrı saklanır. Yetersiz veya bilinmeyen sektörde RS null, confidence 0 ve puan etkisi 0'dır. Sektör isimleri yeniden sınıflandırılmaz veya icat edilmez.

## Rejim

−100/+100 rejim skoru, yalnız mevcut bileşenlerin ağırlıklı ortalamasıdır:

| Bileşen | Ağırlık | Girdi |
| --- | --- | --- |
| BIST100 yönü | .25 | Taze endeks getirisi, ±%3 → ±100 |
| Breadth | .25 | Geçerli evrenin yükselen/düşen dağılımı |
| Kısa trend | .12 | Fiyat/SMA20; Gün İçi fiyat/EMA9 dağılımı |
| Orta trend | .12 | Fiyat/SMA50; Gün İçi fiyat/EMA21 dağılımı |
| Momentum | .10 | Mevcut momentum15 medyanı, varsa |
| Hacim | .08 | Hacim destekli yükselen/düşen dağılımı |
| Sektör dağılımı | .08 | En az üç yeterli sektörün getiri yönü |

Trend/momentum/hacim bileşenleri de yeterli hisse ve kapsama ister. Eksik endeks SMA/momentum/hacim geçmişi uydurulmaz; hazır hisse trendleri açıkça toplu trend bileşenidir. En az üç bileşen, yeterli breadth ve endeks veya trend bileşeni olmadan rejim üretilmez. Confidence kapsama, veri yaşı ve kullanılan bileşen sayısını dikkate alır. Mevcut endeks aralığından volatilite veya hazır volatilite >%5 ise confidence ×0.75 olur.

Rejim confidence <50 veya yeterli veri yoksa BELIRSIZ. Diğer sınıflar GUCLU_YUKSELIS/YUKSELIS/YATAY/DUSUS/GUCLU_DUSUS; score eşikleri ±55 ve ±20. Verisi bilinmeyen veya BELIRSIZ rejim ortak AI confidence'ını yükseltmez.

## Kontrollü puan zinciri

Merkezi/configurable ek etki limitleri:

- `MARKET_REGIME_MAX_EFFECT=0.75`
- `BREADTH_MAX_EFFECT=0.75`
- `SECTOR_RS_MAX_EFFECT=1.0`

Her ayar 0–2 aralığında; toplam net bağlam etkisi ayrıca ±3 ile sınırlıdır. Varsayılan toplam üst sınır ±2.5 puandır. Etki score/100 × confidence/100 × ilgili limittir; confidence <50 veya stale bağlam katkı vermez. Limitler bağlam modeli/sürümü içine dondurulur; environment değişimi geçmiş modelin yorumunu değiştirmez.

Gün İçi: ham puan → kendi sınırlı kalibrasyonu → ayrı piyasa/breadth/sektör düzeltmeleri → `gun_ici_final_puan`. Aynı bağlam shadow puanına uygulanır. Ham `gun_ici_puan` ve `gun_ici_kalibrasyon_duzeltmesi` korunur. Learning kapalı olsa da doğrulanmış piyasa bağlamı küçük etki verebilir; bu, öğrenmenin açılması değildir.

Yarın: `ham_puan + kalibrasyon_duzeltmesi + piyasa_duzeltmesi + breadth_duzeltmesi + sektor_duzeltmesi`, ardından mevcut 0–95 puan sınırı → `final_puan`. Kalibrasyon öncesi/sonrası alanlar ayrı tutulur; shadow aynı bağlamı kullanır. Ham ≥55 aday kapısı ve sert filtreler değişmez.

Ortak AI: mevcut teknik/haber/makro/sektör/fiyat teyidi/geçmiş katkıları korunur. Eski tek-yüzde rejim proxy katkısı yeni sınırlı rejim katkısıyla değiştirilir; breadth ve sektör relatif güç ayrı katkı anahtarlarıdır. Makro sektör olayı ile fiyat tabanlı RS aynı kaynak değildir ve açıklamaları ayrıdır. Bu katman normalize edilmiş teknik/haber ağırlıklarını yeniden öğrenmez; kendi merkezi etki limitlerini kullanır.

Pozitif katkı teknik olarak güçlü hisselerle sınırlıdır (Gün İçi ham ≥65, Yarın/ortak AI teknik ≥70). Negatif haber/makro/sektör, aşırı RSI veya aşırı yükseliş bonus alamaz. Hard eleme ve hedef/stop korunur. Ortak AI'da bağlam öncesi puan AL/SAT ailesinde değilse bağlam tek başına yeni AL/SAT üretemez. Güçlü düşüş+negatif breadth confidence'a −10 verir; Gün İçi için ayrı `gun_ici_baglam_guven` alanında gösterilebilir.

## Snapshot, public rapor ve worker

Public `piyasa_durumu.json`: rejim score/confidence, kullanılan bileşenler, tazelik, breadth/kapsama/sayılar, sektör sıralaması, en güçlü/zayıf sektörler, veri baz/kaynak ve sürüm. Kullanıcı verisi veya secret içermez. Dosya `BIST_DATA_DIR/public` altında; environment yoksa `webapp/data` kullanılır. Standart `/data/piyasa_durumu.json` son hesaplanan kayıttır. `/api/market-context` ayrıca okuma anında seans açık/kapalı etiketini, yaşa göre confidence ve stale durumunu provider çağırmadan günceller; worker durmuş olsa da eski kaydı canlı diye sunmaz. Büyük UI değişikliği yoktur.

Her hisseye yalnız kendi sektörünü içeren küçük `piyasa_baglami` kopyası bağlanır; `piyasa_sektoru` mevcut `makro_sektor` alanını değiştirmez. Gün İçi sinyalinde, Yarın `tahmin` alanında ve ortak AI geçmiş kaydında rejim/breadth/RS/confidence/limit/model sürümü snapshot olarak saklanır. Yarın arşivindeki eski kayıtlar değiştirilmez. Performans motoru bu dondurulmuş bağlamı sonuç kaydına taşır; canlı piyasa JSON'u geçmiş kaydı yeniden puanlamak için kullanılmaz. Future/asof kontrolü kalibrasyon kapsamı seçilmeden önce uygulanır; gelecek bağlam öğrenilmiş rejim ağırlığını bile seçemez.

`market_context` ana motor görevi 300 saniyedir (`MARKET_CONTEXT_INTERVAL_SECONDS`), mevcut `market_open` kontrolüyle piyasa açıkken çalışır. Teknik batch sonrasında da aynı throttled helper çağrılır; taze tam Gün İçi bağlamı daha eksik günlük batch ile ezilmez. Tam Gün İçi tarama kapalı mumlarıyla bağlamı yeniler; Yarın kayıt öncesinde o ana kadar mevcut son seans verisiyle sabitlenir. Aynı gün ikinci Yarın yazımı arşiv kontrolünden döner; bağlam veya snapshot'ı tekrar yazmaz.

Kapalı piyasada `SON_BILINEN_SEANS` etiketi ve gerçek input timestamps korunur. Gün İçi puanlama kapalı piyasada bağlam uygulamaz. Aynı gün kapanış sonrası Yarın bağlamı en fazla 20 dakika yaşında ve yeterli veriliyse kullanılabilir; sonraki güne eski kapanış canlı veri gibi taşınmaz. Uzun kapanış taramasında eskiyen veriler nedeniyle coverage düşerse BELIRSIZ kalması bilinçlidir. Resmi tatil/yarım gün takvimi mevcut ana motor kısıtlarıyla ayrıca doğrulanmalıdır.

JSON atomik replace/fsync ve kilitle yazılır; model sürümü veri+limitlerin içerik özetidir. Tek worker/persistent volume kuralları DATA_PERSISTENCE.md'de geçerlidir. Bu adım deployment veya learning aktivasyonu yapmaz.

## Test

Mock 60 hisselik haritalı evren ve geçici volume: altı rejim, pozitif/negatif breadth ve coverage, güçlü/zayıf/bilinmeyen sektör, stale/future veri, kapalı seans, etki limitleri, ham/kalibrasyon korunması, ortak AI reasons/karar kapısı, immutable snapshot/ortak geçmiş/Gün İçi kaydı, provider yeniden kullanım, worker gate ve HTTP rapor okuması. Gerçek piyasada performans iddiası değildir.
