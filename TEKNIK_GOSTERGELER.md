# Standart teknik göstergeler — 16. adım

`teknik_gostergeler.py` provider çağırmaz. Günlük ve Gün İçi analizlerin mevcut OHLCV sonucunu kullanır. API aynı JSON snapshot'ını okur; ekran için yeniden gösterge hesaplanmaz. Model sürümü `STD_TECH_V1`.

## Tanımlar

- **OBV:** İlk değer sıfır; kapanış yükselirse hacim eklenir, düşerse çıkarılır. Son üç değişimin toplamı/3 kısa eğimdir. Yatay toleransı son dört hacmin ortalamasının %0,5'idir. Kırılım, mevcut değerin önceki 20 OBV değerinin dışına çıkmasıdır. Uyumsuzluk, üç barlık fiyat ve OBV hareketlerinin ters yönlü olmasıdır; pivot/swing formasyonu değildir.
- **Seans VWAP:** HLC3 × hacim kümülatif toplamı / seans hacmi. İstanbul tarihiyle her seans sıfırlanır. 10:00 açılışı ve kesintisiz 5 dakikalık mumlar gerekir. Mesafe ±%0,1 ise yakın; reclaim/kayıp önceki kapanışın kendi VWAP'ına göre taraf değiştirmesidir. Günlük OHLCV gerçek seans VWAP üretmez: `session_value=null`, `UNKNOWN`. Eski 20 bar hacim ağırlıklı referans ayrı `reference_20` olarak korunur ve UI'da VWAP20 referansı yazılır.
- **Bollinger:** 20 kapanış, 2 örneklem standart sapması (`ddof=1`). Bant genişliği `(üst-alt)/orta*100`; ≤%5 sıkışma. Önceki bara göre %10'dan fazla genişleme ayrı alandır. Kırılım ilk dışarı çıkış, banda dönüş önceki dış kapanıştan içeri dönüşdür. Sıkışma+kırılım teyidi: önceki bant genişliği ≤%5, üst kırılım, son hacim/önceki 20 hacim ortalaması ≥%130, pozitif kısa momentum.
- **Momentum:** Üç barlık kapanış ROC yüzdesi (Gün İçi 15 dakika, günlük üç işlem barı); önceki bar ROC farkı ivme. Yön/ivme nötr toleransı ±0,05 yüzde puan. Fiyat eğimi, pozitif/negatif dönüş, son mum yönü ve aralık içindeki kapanış konumu ayrı alanlardır.
- **EMA/RSI/MACD:** Mevcut formüller ortak yardımcıya taşındı. EMA `adjust=False`, MACD 12/26/9, RSI basit 14 bar kazanç/kayıp ortalaması. Günlük RSI'nın eski sıfır-kayıp davranışı uyumluluk seçeneğiyle korunur; Gün İçi yükselen seri 100, düz seri 50.

OBV/Bollinger tek başına karar üretmez. Yeni teyitler mevcut ham/final skora eklenmez.

## Zaman ve eksik veri

Tüm zamanlar `Europe/Istanbul`. Gün İçi bar başlangıcından beş dakika sonrası hesap anını aşamaz. Standart günlük katman 18:10'a kadar günün mumunu dışlar. Mevcut günlük ana analizin canlı fiyatı kullanması korunur; bu nedenle seans içinde eski düz alanlar ile **kapanmış bar** standart alanları farklı zamana ait olabilir. UI standart alanın kendi zamanını gösterir.

Provider `available_at` verirse hesap anından sonra bilinen barlar dışlanır. Gelecek zamanlı provider satırları günlük ana analizden de dışlanır. Ham OHLCV'nin sonradan revize edilmesi `available_at` olmadan tarihsel olarak kanıtlanamaz; bu nedenle dondurulmuş sinyal kayıtları esas alınır ve yeniden üretilmez.

Eksik göstergeler ayrı `UNKNOWN`, `None`, confidence=0 döner. Hacim eksikliği fiyat göstergelerini sıfırlamaz. Gün İçi veri yaşı >20 dakika, günlük veri son kapanmış hafta içi seansından eskiyse stale olur; güven en fazla 35. Stale teyitler shadow katkısı sağlamaz, ortak AI alış kararı güveni 49 ile sınırlanır ve IZLE olur. Resmî tatil/yarım gün takvimi bu katmana eklenmedi; bu günlerde kalite kontrolü muhafazakâr davranabilir.

## Shadow ve kayıtlar

Ağırlıklar isteğe bağlı env ile ayrı ayarlanır; Railway ayarı değişmesi gerekmez:

| Değişken | Varsayılan |
| --- | --- |
| INTRADAY_VWAP_WEIGHT | 0.25 |
| INTRADAY_OBV_WEIGHT | 0.25 |
| INTRADAY_BOLLINGER_WEIGHT | 0.25 |
| INTRADAY_MOMENTUM_WEIGHT | 0.25 |
| TOMORROW_VWAP_WEIGHT | 0 |
| TOMORROW_OBV_WEIGHT | 0.25 |
| TOMORROW_BOLLINGER_WEIGHT | 0.25 |
| TOMORROW_MOMENTUM_WEIGHT | 0.25 |

Her ağırlık 0–1; toplam shadow düzeltme ±2 ile sınırlı. `teknik_ana_skor_etkisi=0`, `teknik_learning_enabled=false`; eski öğrenme açılmış olsa da yeni katkılar otomatik aktive edilmez. Negatif haber/makro/sektör, düşük ham puan, stop, düşük risk/getiri, büyük düşüş/aşırı yükseliş veya aşırı alım koşulu pozitif shadow artışını engeller. Mevcut seçim ve güvenlik filtreleri çalışmaya devam eder.

Gün İçi sinyal geçmişi ve Yarın tarih arşivleri `teknik_gostergeler`, `teknik_katkilar`, `teknik_shadow_puan` içerir. Yarın aynı günün arşivi ikinci yazımla değişmez. Eski kayıtların olmayan göstergeleri tahmin edilmez ve `--` gösterilir. API eski `analiz_kimligi` hash davranışını korur; zamanla değişen stale görünümü AI alarm kimliğini değiştirmez.

## Performans raporları

Mevcut public `gun_ici_performans.json` ve `performans_ozeti.json` içine `standart_teknik_kriterler` eklenir. Özel sinyal geçmişleri/private/runtime dizinleri aynı kalır. UI Ölçüm sayfasında raporlar ayrı gösterilir.

Gün İçi: 5/15/30/60 dakika + SEANS. Yarın: 1/3/5/10/20/60 işlem günü. Her biri 10 kriteri varken/yokken/bilinmeyen olarak ölçer: VWAP üstü/reclaim; OBV trend/kırılım/pozitif ve negatif uyumsuzluk; Bollinger sıkışma-kırılım/banda dönüş; momentum güçlenme/zayıflama. Örnek sayısı, başarı oranı, medyan, trimmed mean, Wilson aralığı ve confidence tutulur.

Örnekleme sonuç seçmeden önce ilk hisse/gün sinyalini sabitler. Yarın yalnız ana `YARIN_TOP10`, Gün İçi yalnız AL kayıtları; başka mode göstergeleri bilinmeyendir. Yalnız tamamlanmış, kaliteli, sinyal sonrası ve rapor zamanından önce gözlenen sonuçlar kullanılır. Başarı tam `BASARILI`; kısmi sonuç başarı oranında tam kazanım sayılmaz. Yeterli güven için hem kriter varken hem yokken en az 40 örnek ve beş bağımsız gün gerekir. Bu rapor mevcut ağırlık öneri/aktivasyon mekanizmasını değiştirmez.

## Doğrulama

Yeni testler: `tests/test_teknik_gostergeler.py`, `tests/test_teknik_performans.py`, `tests/test_teknik_ui.cjs`. Mock barlar/provider ve geçici veri kökleri kullanılır. Gelecek/açık mum, geç gelen veri, iki mode, immutable arşiv, stok HTTP API ve hard safety sınanır. Mevcut Python regresyonları ve iPhone boyutlu Chromium PWA/Safari smoke grupları ayrıca çalıştırılır; gerçek iPhone/WebKit testi değildir.
