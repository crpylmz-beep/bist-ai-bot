# Sinyal ölçümü ve Yarın TOP10 kalibrasyon hazırlığı

`performans_motoru.py` mevcut `ai_ogrenme_gecmisi.json/kayitlar` listesini kullanır. ORTAK_AI/GUN_ICI kayıtları korunur. Immutable Yarın arşivi yalnızca okunur; YARIN_TOP10 sinyalleri tarih/içerik-hash/sembol kimliğiyle aynı geçmişe bir kez eklenir. Canonical haber ve makro olayları da kaynak/event/sembol kimliğiyle tek örnektir. Snapshot ve mevcut Yarın canlı JSON'u değiştirilmez.

## Vadeler ve veri kalitesi

1/3/5/10/20/60 işlem seansı; HABER/MAKRO için 1/3/5 seans desteklenir. Yarın ana metriği bir sonraki işlem seansıdır. Sinyal günü sayılmaz, hafta sonu dışlanır; `holiday(date)` callback'i resmi tatil takvimi için enjekte edilebilir. Varsayılan hafta içi takviminde eksik beklenen gün varsa sonuç sonraki mevcut bara kaydırılmaz, VERI_YETERSIZ olur. Resmi tatil/yarım gün takvimi henüz otomatik bağlı değildir.

Geçmiş günler veya bugün İstanbul saatinde 18:15 sonrası tamamlanmış günlük OHLC kullanılır. Gelecek/incomplete mum, çelişen aynı gün verisi, sıfır/negatif/NaN fiyat, OHLC tutarsızlığı ve eksik seans geçerli sonuç oluşturmaz. Eksik sonuç tamamlanmadı olarak kalır ve yeniden denenir. Referans fiyat sinyal/tahmin içinde saklanan fiyattır; bugünkü fiyat baz fiyat yerine yazılmaz.

Her vade başlangıç/kapanış, ham getiri, karar yönüne göre getiri, maksimum yükseliş/düşüş, hedef/stop teması, ilk temas, en iyi/kötü fiyat, risk/getiri, sonuç/gözlem tarihi ve tamamlama göstergesi taşır. Long: stop < referans < hedef. GUN_ICI SAT mevcut ters mesafe yaklaşımıyla uyumludur. Diğer SAT kayıtlarında gerçek short seviyeleri yoksa hedef/stop başarısı uydurulmaz; kapanış getirisi yine ölçülebilir.

Aynı günlük mumda hedef ve stop görülüp açılış ikisinin arasındaysa sıra BELIRSIZ; hedef_once/stop_once null olur. Açılış gap'i veya farklı günlerde ilk temas sırayı gösterebilir. Belirsiz sıra kalibrasyona girmez. Tamamlanan vade sonucu yeni fiyatlarla overwrite edilmez. Eski close-only sonuçları da korunur, bulunmayan risk başarısı icat edilmez. `AIKararMotoru.measure()` ortak ölçüme delege olur; eski close-only API çalışır, tam OHLC yoksa başarı sınıfı yetersizdir. Ortak geçmiş katkısı yetersiz/belirsiz sonuçları başarı örneği saymaz.

## Başarı tanımı

R, referans-stop mesafesidir; pozitif kapanış tek başına başarı değildir.

- STOP: İlk kesin temas stop.
- BASARILI: İlk kesin temas hedef; veya geçerli seviyelerle yön getirisi en az 1R, ters hareket 1R'den küçük.
- KISMEN_BASARILI: Temas yokken pozitif yön getirisi en az .5R.
- BASARISIZ: Başarı koşulları sağlanmadı.
- VERI_YETERSIZ: Eksik/hatalı fiyat, referans/level veya bilinmeyen temas sırası.

Yarın tahmini long potansiyeli olarak değerlendirilir. Hedef ve stop temas sayıları ayrı ham metriklerdir; hedef sonradan görülse de stop önceyse sınıf STOP'tur. Snapshot sıra/skor/fiyat/AL/hedef/stop/karar/kriterleri kopyalanır; kaynak dosya byte'ları değişmez. `runtime/yarin_top10_sonuclar.json` ayrı private sonuç projeksiyonudur; asıl sinyal/vade kaydı mevcut öğrenme geçmişindedir.

## Raporlar

Public JSON, mevcut `/data/` HTTP yolu üzerinden okunur; büyük UI eklenmedi.

- `performans_gunluk.json`: Tahmin tarihine göre liste, ayrıca sonuç tarihi; ortalama/medyan/%10 trimmed ortalama, pozitif/negatif/nötr, hedef/stop, en iyi/kötü, TOP3/TOP5/TOP10, skor/sıra korelasyonu, yüksek/düşük skor grupları, beklenen/değerlendirilen kayıt ve tamamlanma.
- `performans_ozeti.json`: Altı vade, model/sektör/rejim, son 20 tamamlanan sonuç işlem günü, TOP3/TOP10 ve skor ilişkisi, genel/Yarın/sektör/rejim kriter raporları, 3/5 günlük kriter karşılaştırmaları.
- `onerilen_agirliklar.json`: Mevcut/önerilen ağırlıklar, kriter yönleri, gerekçeler, örnek sayıları, learning durumu; otomatik_uygulandi=false.

Eksik günlük liste son20 karşılaştırmasına kısmi başarı olarak alınmaz. Başarı sınıfı bilinmeyen ama kapanış getirisi bilinen kayıt fiyat özetine katılabilir; başarı oranı paydası ayrıca gösterilir. False-positive/negative ve TP/FP/TN/FN yalnızca kayıtlı AL/SAT/IZLE örneklerinden ölçülür; seçilmeyen bütün piyasada yanlış negatif bilindiği iddia edilmez. Kriter ilişkisi nedensellik değildir.

## Kriterler, güven ve öneriler

RSI, MACD, SMA/trend, hacim, VWAP, OBV, Bollinger, momentum, destek/direnç, R/R, haber/KAP, makro/sektör, fiyat teyidi, rejim ve geçmiş katkı için var/yok karşılaştırması vardır. Bilinmeyen gösterge yok sayılmaz. İlk etiketler `criteria()` içinde açıktır: RSI 30–65; MACD>signal veya hist>0; SMA20>SMA50; hacim>=150%; VWAP üstü; OBV yükselen; bant içinde; momentum15>0; destek<direnç; R/R>=1.5; katkı mevcutsa ilgili olay kriteri var. Bunlar mevcut teknik algoritmayı değiştirmez.

Her grup örnek/ortalama/medyan/trimmed ortalama, sıkı BASARILI oranı ve %95 Wilson aralığı taşır. Başarı farkının konservatif aralığı, yeterli/yetersiz veri ve farklı sinyal günü sayısı gösterilir. RSI düşük+MACD negatif ve makro negatif kombinasyonları da raporlanır.

`MIN_LEARNING_SAMPLES=40` varsayılan, 30–10000 arası ayarlanabilir. Öneri için her iki var/yok grubunda minimum kadar örnek ve en az beş farklı gün gerekir. Başarı farkı aralığı sıfırı dışlamalı, medyan farkı en az .25 puan olmalıdır. Tek outlier ortalamayı değiştirse de tek başına öneri doğurmaz. Yarın önerisi kendi ertesi seans sonuçlarından çıkar; yetersiz veri mevcut ağırlıkları aynen önerir.

Kriter ARTIR/AZALT/SABIT yönü merkezi AI grubuna .0025 küçük adımla çevrilip min/max ve ±.005 sınırlarında normalize edilir. Yarın özel algoritması bu adımda değiştirilmez. **LEARNING_ENABLED=false varsayılan. Kapalı veya açıkken performans görevi yalnızca öneri yazar, ağırlık dosyasını değiştirmez.** Açıkken ayrıca çağrılabilecek `update_weights()` minimum gerçek tamamlanmış örnek ister ve gün başlangıcından toplam .005 sınırını korur. Otomatik optimizer/kaynak kodu düzenleme yoktur.

## Olay referansları

Canonical haber bilinen ilk fiyatı veya private ilk AI gözlem baseline'ını kullanır. İlk gözlem yayın fiyatı değildir; tür/zaman ayrıca kayıtlıdır. Referans yoksa VERI_YETERSIZ/REFERANS olarak öğrenme dışında kalır. KAP/site aynı olayın iki örneğini üretmez. Makro yayınında mevcut hisse bazlı zaman damgası en fazla 20 dakika eski fiyat ve quote zamanı saklanır; eksik/eski fiyat uydurulmaz. Event tekrarı ilk referansı overwrite etmez. Geçmişte tutulmamış olay fiyatı geriye dönük biliniyormuş gibi yaratılmaz.

## Worker ve yollar

`bekleyen_sonuclari_guncelle()` tek tur fonksiyonu; ana motor `performance` görevi 900 saniye (`PERFORMANCE_INTERVAL_SECONDS`). `PERFORMANCE_BATCH_SIZE=10` (1–25), turda en fazla 100 sinyal; semboller arasında kayıt kotası paylaşılır. Yalnızca vadesi gelmiş açık kayıtlar provider'a gider. Fiyat aynı sembol için bir kere okunur; günlük cache kapanışta yenilenir, eksik/hatalı kayıt 6 saat sonra yeniden denenir. Tamamlanan/vadesi gelmeyen veya referansı olmayan kayıt için gereksiz fiyat çağrısı yapılmaz. Rapor değişiklikte veya saatlik güncellenir. Ana motor hata/backoff'u izler, diğer işler devam eder.

Provider teknik motorun mevcut `bist_bot.bp.Ticker(...).history(period='1y')` yoludur. Bir yıllık kapsam dışında/eksik geçmiş yetersiz kalır. Provider çağrısı history flock'unu tutmaz; güncelleme mevcut AI yazıcısıyla aynı lock ve atomic write kullanır.

BIST_DATA_DIR altında history, performans_durum, performans_fiyat_cache ve yarin_top10_sonuclar runtime/private; raporlar public, immutable snapshot archives içindedir. Env yokken legacy local yollar korunur ve web server private eski dosyaları sunmaz. Kullanıcı alarm/push verileri ve teknik/TOP10 iş mantığı değişmez. Testler mock OHLC ile yapılır; deployment yoktur.
# Yarın kalibrasyon bağlantısı (on üçüncü adım)

Tamamlanmış ertesi işlem günü sonuçları ayrı `yarin_kalibrasyon.py` katmanına kanıt sağlar; ham algoritma korunur. Yeni tahminlerde birlikte dondurulan ham/shadow listeleri YARIN_BASELINE/YARIN_SHADOW modelleriyle ayrı ölçülür ve kriter eğitimine karıştırılmaz. Learning varsayılan kapalıdır. Günlük limit, kanıt filtreleri, ileriye dönük karşılaştırma ve rollback için YARIN_KALIBRASYON.md'ye bakın.
