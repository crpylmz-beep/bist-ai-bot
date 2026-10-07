# Kontrollü performans ve ağırlık önerileri — 18. adım

Mevcut `performans_motoru.py` istatistikleri genişletildi; ikinci provider/worker/öğrenme motoru kurulmadı. Gün İçi ve Yarın kalibrasyonunun mevcut dosyalarına `controlled_evidence` alanı eklenir. Aktif ana model, karar eşikleri, eski rollback geçmişi ve dondurulmuş arşivler değiştirilmez. Yeni öneriler yalnız ayrı shadow alanında kullanılır.

## 36 kriter ve aileleri

- trend: SMA trend, EMA trend, MACD;
- momentum: RSI, kısa momentum;
- hacim: hacim, OBV trend/kırılım/pozitif ve negatif uyumsuzluk, hacimli kırılım;
- fiyat_konumu: seans VWAP, reclaim, Bollinger sıkışma/kırılım, destek/direnç;
- volatilite: ATR/fiyat oranı ve risk/getiri;
- piyasa: pozitif/negatif rejim ve breadth;
- sektor: güçlü/zayıf relatif güç;
- haber: KAP, şirket sitesi, pozitif/negatif haber, fiyat teyidi;
- makro: pozitif/negatif etki;
- karar: GUCLU_AL/AL/BEKLE/SAT/GUCLU_SAT (ölçüm amacıyla; ağırlığı sıfır).

Göstergeler yeniden hesaplanmaz; sinyalde dondurulmuş standart gösterge/analiz girdileri okunur. Eksik, yanlış zaman dilimindeki, gelecekteki veya stale alanlar bilinmeyen sayılır. Negatif gözlem gibi kullanılmaz. EMA kısa veride, gerçek seans VWAP intraday'de bulunabilir; günlük OHLCV'den seans VWAP uydurulmaz.

## Örnekleme ve başarı

Sinyal yönü, hedef/stop ve sırası, risk/getiri ve kullanım süresini hesaplayan mevcut sonuç motorları aynen kullanılır. Sırf pozitif kapanış başarı sayılmaz. Tam BASARILI kazanımdır; kısmi başarı ayrı sayılır. Ambiguous aynı-mum temas, eksik OHLC, tamamlanmamış veya kalitesiz sonuç kalibrasyona girmez. SAT/BEKLE karar kırılımları ilgili kaydın mevcut yön/sonuç etiketlerini betimler; yeni short/BEKLE işlem simülatörü değildir.

Örnekleme önce ilk hisse/gün sinyalini seçer, sonra sonucun uygunluğuna bakar; kötü ilk sonucu ikinci iyi sinyalle değiştirmez. Ana günlük eğitim yalnız YARIN_TOP10, Gün İçi eğitim AL kayıtlarıdır. Eski baseline/shadow tekrarları eğitim sayısını şişirmez.

Vadeler ayrı tutulur: Gün İçi 5/15/30/60 dakika + SEANS; günlük 1/3/5/10/20/60 işlem günü. Her kriter için varken/yokken/bilinmeyen, örnek ve farklı gün sayısı, başarı/failure/kısmi başarı, oran, medyan, trimmed mean, ortalama, en kötü/en iyi, hedef/stop oranı, Wilson aralığı ve confidence vardır. Bilinmeyen hedef/stop oranı `null` olur. Adverse excursion sinyal sonrası yönle uyumlu fiyat olumsuzluğudur; portföy maksimum drawdown değildir.

Öneri için **iki grupta da en az 40 örnek ve beş farklı hafta içi sinyal günü** gerekir. Config:

- `MIN_LEARNING_SAMPLES`: eski değişken korunur; yeni ölçümde alt sınır 40;
- `MIN_LEARNING_DAYS`: varsayılan 5, aralık 5–250;
- `CONTROLLED_REPORT_INTERVAL`: ağır yeni toplu ölçümler için varsayılan 3600 saniye, aralık 60–86400. Worker interval/batch değiştirilmez.

Resmî tatil takvimi yeni ölçüm katmanına eklenmedi; fiyat/sonuç motorunun mevcut seans doğrulaması esas alınır.

## Öneri, aile bütçesi ve çifte sayım

Wilson başarı farkı aralığı sıfırın tek tarafında olmalı ve medyan farkı en az 0,25 yüzde puanla aynı yönü teyit etmeli. Sırf daha iyi ham oran yeterli değildir.

Geçerli kriter çiftlerinde ≥%85 aynı bayrak bulunan kriterlerden tek temsilci tutulur. Bu kontrol aileler arasında da uygulanır; tam bir nedensel veya ML bağımsızlık testi değildir.

Sabit normalize aile bütçeleri: trend .15, momentum .15, hacim .15, fiyat konumu .15, volatilite .10, piyasa .08, sektör .06, haber .10, makro .06, karar 0. Toplam 1. Bunlar ek shadow ölçüm katsayılarıdır; ana `ai_agirliklari.json` katsayılarıyla değiştirilmez.

Aile içinde güvenilir artır/azalt kanıtı birlikte varsa en fazla .0025 karşılıklı aktarım önerilir. Her kriter BASE×.5–BASE×1.5 aralığındadır; gün başlangıcına göre toplam hareket ≤.005. Her aile bütçesi sabit kalır; tüm model körlemesine yeniden küçültülmez. Öneride mevcut/önerilen ağırlık, fark, örnekler, başarı farkı, confidence, neden, aile, min/max, veri tarihi ve model sürümü bulunur. Karşılıklı kanıt yoksa aktarım yapılmaz.

## Prospective shadow ve promotion

Shadow model sürümü, oluşturma zamanı, kaynak, parent, gerekçe, eğitim cutoff'u ve eğitim kimlikleri private runtime'a kaydedilir. Eğitim kimlikleri public rapora çıkmaz. Aktif shadow seti ayrı değerlendirme biriktirebilmesi için yedi takvim günü sabit tutulur; henüz pasifken ilk yeterli kanıt oluşursa shadow başlatılabilir. Ana modelin aktivasyonu değildir.

Mevcut analiz/cache sonuçlarıyla yeni sinyale ayrı `controlled_shadow` skor/metadatası eklenir. Fark toplam ±2 puanla sınırlıdır. Stop, negatif haber/makro/sektör, sert düşüş, aşırı yükseliş, düşük RR, stale ve nihai güvenlik engeli pozitif bonusu durdurur. Geçersiz/future model bütçesi BASE/etkisiz olur. Ana ham/final puan ve nihai karar değişmez.

Yarın arşivinde `controlled_shadow_top10` ayrı ve ilk yazımda dondurulmuş listedir. Yeni ithal kayıt modeli `YARIN_CONTROLLED_SHADOW`; ana eğitim havuzundan dışlanır. Gün İçi kontrollü shadow adayları mevcut sinyal geçmişinde üyelik bayrağıyla saklanır. Daha sonraki fiyat/haber/rejim/model bu kayıtları yeniden puanlamaz.

Kıyas yalnız eğitim cutoff'undan **sonra oluşturulmuş**, aynı shadow sürümünü gerçekten kaydetmiş sinyallerin daha sonra tamamlanmış sonuçlarıdır. Eğitim kimlikleri ve future sonuçlar dışlanır. Her cohort hisse/gün örneklemesiyle dedup edilir. Eğitim cohort'u validation başarısı olarak sunulmaz.

Promotion candidate için iki cohort'ta minimum örnek/gün, Wilson farkının pozitif olması, medyan üstünlüğü, hedef oranında gerilememe, stop/adverse-excursion riskinde kötüleşmeme aranır. Eksik risk kanıtıyla adaylık verilmez. Otomatik promotion/rollback/ana eşik değişimi yoktur.

## Diğer kırılımlar

Karar + confidence: 0–49, 50–60, 60–70, 70–80, 80+ (aralıklar alt sınır dahil/üst hariç). Teyit: 3,4,5,6+ ve varsa diğer sayılar. Rejim ve sektör bazında kriter ölçümü vardır; sektör özel ağırlık otomatik üretilmez/uygulanmaz.

Canonical haberler mevcut event kayıtlarında yakalanmış metadata ile ölçülür. Türler bilanço, sözleşme, yatırım, sermaye, dava/ceza, ortaklık, ihale, satış, üretim, temettü, OTHER; yalnız açık kaynak etiketi ve ≥70 confidence kullanılır. Metinden yeni kategori tahmini yapılmaz. Sonradan gelen metadata geçmiş olayın sınıflamasına geri katılmaz. Haber türleri mevcut haber sonuçlarıyla 1/3/5 günde ölçülür; sadece hisseyle aynı gün başka haber geldi diye o haberin etkisi olduğu iddia edilmez.

## Dosyalar ve UI

Public: `kriter_performansi.json`, `shadow_model_ozeti.json`, mevcut `onerilen_agirliklar.json` içinde `kontrollu_olcum`. Her dosya DAILY/INTRADAY alanlarını ayrı tutar. Kilit + atomik yazım eşzamanlı modların birbirini ezmesini önler. Eski öneri alanları korunur.

Private: mevcut `yarin_kalibrasyon.json` ve `gun_ici_agirliklari.json` içindeki `controlled_evidence` model/eğitim geçmişi. Aktif ana AI ağırlık dosyası, özel alarm/push/kullanıcı verileri değişmez. `BIST_DATA_DIR` ve mevcut path helper'ları kullanılır.

Kapalı sonuç fingerprint'i değişmediyse istatistikler yeniden kurulmaz. Değişiklikler ağır rapor aralığında biriktirilir; mevcut sonuç motoru sadece pending vadeleri ve sınırlı sembol batch'ini işler. Rapor hesapları yeni network geçmiş çağrısı yapmaz. İlk açılışta veya eksik public çıktı halinde raporlar yeniden oluşturulabilir.

Mevcut AI Öğrenme ekranına Model Performansı eklenir: ayrı ana/shadow doğrulama başarısı, örnek sayısı, yeterli kanıtlı güçlü/zayıf beş kriter, son model güncellemesi, Learning KAPALI, Shadow AKTİF/PASİF. Yetersiz veri açıkça gösterilir. Hisse detayı değiştirilmedi; rapor JSON'ları mevcut web static veri API'sinden erişilir.

Yeni testler `tests/test_kontrollu_ogrenme.py` ve `tests/test_model_performansi_ui.cjs`; tam Python ve JS/browser regresyonları ayrıca çalıştırılır. Gerçek piyasa veya push servisi kullanılmaz. Cloud başlatıcı/web/worker süreçleri, volume, VAPID, push ve /health değiştirilmedi. Eski opt-in kalibrasyon/rollback altyapısı korunur; yeni öneriler learning env'i açık olsa da otomatik ana modele uygulanmaz.
