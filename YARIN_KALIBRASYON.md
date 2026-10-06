# Yarın TOP10 kontrollü kalibrasyonu

`yarin_potansiyel_hesapla` değiştirilmedi. `yarin_kalibrasyon.py` mevcut ham puanın üzerine sınırlı ve açıklanabilir bir düzeltme uygular. Varsayılan `LEARNING_ENABLED=false`: ana puan ve sıralama aynı kalır; performans, öneri ve shadow ölçümü devam eder. Otomatik aktivasyon yoktur.

## Mevcut ham puan envanteri

| Kriter | Mevcut puan katkısı |
| --- | --- |
| Trend/SMA | Fiyat>SMA20 +18, aksi −8; fiyat>SMA50 +12, aksi −6; SMA20>SMA50 +10, aksi −5. Maksimum +40. |
| RSI | 45–60 +15; 40–45 veya 60–64 +10; 35–40 +5; 64–68 +4; 30–35 +1; 68–70 −4. |
| MACD | MACD>signal +12, aksi −6; histogram pozitif +8, aksi −4; yukarı kesişim +8. Maksimum +28. |
| Hacim | Oran ≥150 +10; ≥120 +7; ≥100 +4; ≥80 +1; ≥70 −3; ≥60 −7; diğer pozitif oran −12. |
| Günlük momentum | (0,2.5] +8; (2.5,4] +6; (4,5] +3; (5,6] −8; (6,7) −15; (−1,0] +1; (−2,−1] −5; (−3,−2] −10. |
| Dirence mesafe | %7–25 +7; %5–7 +5; %3–5 +2; %0–3 −7; %25–40 +2; direnç fiyatın altında/eşit −3. |
| Risk/getiri | ≥3 +7; ≥2 +5; ≥1.5 +2; (0,1) −6. |
| Uyum | Güçlü trend+MACD +6; güçlü trend+uygun RSI+hacim +4; fiyat SMA20 altında ve yalnız MACD pozitif −5. |
| Haber/KAP, makro, sektör, fiyat teyidi | Mevcut haber birleştirme ve dinamik etki fonksiyonları; sabit yeni puan eklenmedi. |

Teknik toplam 0–95 aralığında sınırlanır; mevcut haber birleştirme sonucu ve seviyeler korunur. Fiyat≤0, günlük değişim≤−3 veya ≥7, RSI<30 veya ≥70, pozitif hacim<70 ve günlük değişim>6 gibi mevcut eleme kuralları aynen çalışır. Ham aday eşiği 55 değişmez.

## Kanıt, etki ve güvenlik

Kalibrasyon kriterleri RSI, MACD, SMA_TREND, HACIM, MOMENTUM, DESTEK_DIRENC, RISK_GETIRI, HABER, MAKRO, SEKTOR ve FIYAT_TEYIDI'dir. Haber/KAP tek kriterdir. OBV/Bollinger için hayali gözlem üretilmez; VWAP mevcut haber motorunun bağlamında kalır, bağımsız öğrenme katsayısı eklenmez. Bilinmeyen alanlar karşılaştırma gruplarına dahil edilmez.

Yalnız tamamlanmış YARIN_TOP10 ertesi işlem günü sonuçları kullanılır. Her kriterin mevcut/eksik iki grubunda en az 40 örnek (`MIN_LEARNING_SAMPLES`, 40 altına düşmez), her grupta en az 5 farklı sonuç işlem günü, yeterli güven, sıfırı dışlayan %95 Wilson fark aralığı ve yönü destekleyen medyan farkı gerekir. Mevcut performans motorunun medyan ve %10 trimmed ortalaması korunur. Shadow/baseline kayıtları eğitim örneklerine eklenmez.

Kalibrasyon katsayıları ham algoritmanın puan ağırlıkları değildir: 11 eşit nötr katsayıdan (1/11) başlayan ayrı bir düzeltme modelidir. Her katsayı başlangıcın 0.5–1.5 katı aralığında, toplamı 1 olacak şekilde tutulur. Gün başlangıcına göre değişim katsayı başına en fazla 0.005; kanıtlı öneri adımı 0.0025'tir. Normalizasyonla hareket eden onaysız kriterler puana katkı yapmaz.

`final_puan = ham_puan + kalibrasyon_duzeltmesi`; puan aralığı 0–95. Toplam etki varsayılan ±3 puandır. `YARIN_CALIBRATION_MAX_POINTS` 0–5 arasında ayarlanabilir. Sektör/rejim için aynı örnek ve güven şartları aranır; her geçerli kapsam %15 karışım yapar, yetersiz veya bilinmeyen kapsam genel modele döner. Negatif haber/makro/sektör, günlük yükseliş>%4 veya RSI≥64 varsa pozitif kalibrasyon katkısı engellenir. Elenmiş adaylar geri alınmaz; hedef/stop/AL seviyelerine kalibrasyon yazmaz.

## Snapshot ve shadow

Kapanış tahmini yazılmadan önce `freeze_day()` İstanbul günü için modeli dondurur. Aynı gün ikinci yazım snapshot'ı veya kullanılan modeli değiştirmez. Tahmin kaydı ham_puan, kalibrasyon_duzeltmesi, final_puan, shadow_puan, calibration_version ve shadow_version taşır; kriter katkıları satırda ayrıca saklanır.

Yeni arşivlerde ana `top10`, ham sıralamalı `ham_top10`, öğrenilmiş sıralamalı `shadow_top10` ve `kalibrasyon_modeli` tahmin anında birlikte kaydedilir. Shadow tüm uygun adaylardan seçilir; yalnız ana TOP10'u yeniden sıralamakla sınırlı değildir. Sonradan gerçekleşen sonuçla geçmiş sıralama üretilmez. Eski arşivlere yeni alan yazılmaz; eski arşivler shadow karşılaştırması yokken de okunur.

Performans motoru YARIN_BASELINE ve YARIN_SHADOW sonuçlarını ayrı takip eder. Her iki listenin tüm üyelerinin ertesi işlem günü sonucu tamamlanan son 20 karşılaştırma günü public rapora dahil edilir; ortalama, medyan ve trimmed ortalama ayrı hesaplanır. Bu ölçümler henüz gerçek piyasa başarısı iddiası değildir.

## Dosyalar, sürümleme ve rollback

`BIST_DATA_DIR` varsa özel model `runtime/yarin_kalibrasyon.json`, sürüm projeksiyonu `runtime/yarin_agirlik_gecmisi.json`; yoksa `.local/runtime/` kullanılır. Ana dosya tek doğruluk kaynağıdır, sürümler içerik özeti ve gün ile kimliklenir ve saklanır. JSON yazımı atomiktir; model ve ortak performans geçmişi dosya kilitleriyle okunur/yazılır. Public `kalibrasyon_durumu.json` katsayı deposunu veya kullanıcı verisini içermez.

Admin rollback örneği:

```python
from yarin_kalibrasyon import YarinKalibrasyon
YarinKalibrasyon().rollback('BASE')  # veya geçmişteki bilinen sürüm kimliği
```

Rollback mevcut günün tahminini değiştirmez. Sonraki gün öğrenme açıksa seçilen hedefe günlük 0.005 sınırında dönüş başlar; uzak sürüme dönüş birkaç gün sürebilir. Hedef yeni bir rollback seçimine kadar korunur. Rollback learning'i açmaz. `LEARNING_ENABLED=false` güncel sıralamada kalibrasyonu kapatır; kapalı dondurulmuş model aynı gün environment açılarak etkinleştirilmez. Mevcut arşivlere dokunulmaz.

Lookahead için sonuç `observed_at`, tahmin zamanı, sonuç işlem günü ve model `asof` kesimleri kontrol edilir. Gelecekte hesaplanmış model geçmiş zamana uygulanmaz. Ana motor performans görevi sonrasında günde en fazla bir kez önerileri yeniler; kapanışta son mevcut kanıtla bir ek sabitleme yapılır. Kalibrasyon hatası diğer worker görevlerini durdurmaz.

## Doğrulama

`python -m unittest discover -s tests -q`: kapalı/açık learning, 40 örnek/5 gün/güven, günlük ve toplam limitler, kapsam fallback, sürüm/rollback, immutable snapshot, güvenlik, outlier/lookahead, ileriye dönük shadow sonuçları, worker izolasyonu ve HTTP public/private ayrımı. Testler geçici volume, mock saat/fiyat sağlayıcısı kullanır; gerçek kullanıcı kayıtlarına yazılmaz.
