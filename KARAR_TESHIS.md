# Kombinasyon ve algoritma sağlığı — 19. adım

İkinci öğrenme/provider/worker motoru yoktur. `performans_motoru.py` içindeki mevcut kapanmış sonuç raporlama hattı genişletilir. Gün İçi ve günlük vadeler ayrı tutulur; ana karar, seçim, eşik, ağırlık ve cloud süreçleri değiştirilmez. Yeni kombinasyon katkıları **yalnız öneridir**, mevcut 18. adım shadow skoruna bile otomatik eklenmez. Learning kapalıdır.

## Kontrollü kombinasyonlar

Sinyalde gözlenen mevcut 36 kriterden ikili/üçlü setler üretilir. Yalnız bilinen girdi kapsamına göre seçilir; başarı/getiriyle en iyi görünen kombinasyonları tarayarak vocabulary seçilmez. Varsayılan üst sınır 64; dörtte bire kadar yer üçlülere ayrılır. Veri eksikse daha az veya sıfır kombinasyon çıkar. Tek aileden EMA/SMA/trend gibi tekrarlar engellenir. Haber polaritesi + fiyat teyidi bağımsız teyit olarak aynı haber ailesi içinde tek istisnadır. Negatif haber + teknik bozulma için `!MACD`, `!SMA_TREND`, `!EMA_TREND`, `!MOMENTUM` literal bayrakları sinyaldeki bilinen false değerlerden türetilir; bilinmeyen false sayılmaz.

Varsayılan minimum **kombinasyon varken ve yokken ayrı ayrı 50 örnek / 7 İstanbul işlem günü**. Bilinmeyen kriterler yok grubuna dönüştürülmez. Küçük cohort sayıları görünür, başarı/getiri yüzdeleri `null`; güçlü etiketi/katkı yoktur. Wilson fark aralığı tek tarafta ve medyan farkı aynı yönde >0,25 puansa ±0,25 shadow puan önerisi oluşabilir. Kaynak güven katsayısı bu öneriyi küçültür. `applied=false`; politika en fazla bir kombinasyon ve ilgili tekil bonusların yerine kullanma, üst üste eklememe. İleride bir uygulama açılacaksa ayrı onay/güvenlik doğrulaması gerekir.

Her vade/kaynak için örnekler, farklı günler, başarı, medyan/trimmed mean, hedef/stop, confidence, rejim/sektör dağılımı ve ölçülen sinyal model sürümleri raporlanır. Yeni sinyallerde `controlled_shadow.criteria_snapshot` kriter bayrakları, zaman ve model sürümünü dondurur. Eski snapshotlar değiştirilmez; legacy ölçüm kendi dondurulmuş analiz alanlarından okunur.

## Kaynak ayrımı

`performance_source` = LIVE/BACKTEST/SHADOW. Açık bilinmeyen kaynak eğitimden dışlanır. Eski gerçek snapshot/AI/Gün İçi kayıtlarında LIVE, ayrı shadow modellerinde SHADOW, BACKTEST modelinde BACKTEST varsayılır. Backtest kayıtları açık `performance_source=BACKTEST`, `performance_mode`, sinyal zamanı, `decision_asof` ve `model_created_at` metadata'sıyla mevcut geçmişte tutulabilir. Yeni backtest simülatörü kurulmadı ve sonuç uydurulmadı.

Kaynaklar ve vadeler ayrı havuzlardır; örnek sayıları birleştirilmez. Mevcut ana canlı ağırlık önerileri backtest/shadow kayıtlarını kullanmaz. LIVE güveni varsayılan 1, BACKTEST .5, SHADOW .75; configurable güven yalnız yeni ayrı kombinasyon önerisini ölçekler. 18. adımın canlı kriter ağırlıkları ve prospective validation kuralları korunur. Intraday shadow yalnız frozen üyelik, uygunluk ve eğitim cutoff'undan sonraki sinyallerle ölçülür.

Gelecek/eksik model provenance, gelecekte tamamlanan sonuç, future gösterge/haber/makro/piyasa bağlamı geçmiş değerlendirmeye geri sokulmaz. İlk hisse/gün/model kaydı sonuç uygunluğundan önce seçilir; iyi ikinci sinyalle kötü ilk sinyal değiştirilmez. Zamanları Europe/Istanbul olarak değerlendirir. Resmî tatiller için sonuç motorunun mevcut seans doğrulaması esas; yeni resmî tatil takvimi eklenmedi.

## Hata günlüğü ve kalite

Private `runtime/karar_hata_gunlugu.json`, kaynak/mode/vade/sinyal kimliğiyle idempotent atomik birleştirilir. Symbol, frozen sinyal/karar/skor/confidence, hedef/stop, gerçek sonuç, hata tipi(leri), gerekçe, kaçan risk, yanıltıcı kriterler, rejim/sektör/haber bağlamı ve sinyal model sürümü vardır. Eski model sürümü bilinmiyorsa `LEGACY_UNKNOWN`; bugünkü model geçmişe atanmaz.

Sınıflar: FALSE_AL, FALSE_SAT, STOP_TOO_TIGHT, TARGET_TOO_AGGRESSIVE, LATE_ENTRY, EARLY_ENTRY, VOLUME_FALSE_BREAKOUT, NEWS_FALSE_POSITIVE, MARKET_CONTEXT_MISSED, SECTOR_CONTEXT_MISSED, STALE_DATA_ERROR, UNKNOWN. Bir sinyal birden fazla sınıf taşıyabilir. Gerekçeler frozen girdilere dayalı **tanısal ilişkilerdir; kanıtlanmış nedensellik değildir**. Kayıtlı gerçek short yön/sonuç bulunmadan FALSE_SAT veya kaçırılmış tüm piyasa fırsatlarından false negative üretilmez. Gün İçi SAT mevcut motorun referans sonucudur; yeni short simülasyonu yoktur.

ATR varsa stop mesafesi <.75 ATR / ulaşılmayan hedef >4 ATR tanısal bayrakları; explicit giriş teyidi ve kayıtlı sinyal yaşı varsa erken/geç giriş sınıfları üretilir. Negatif rejim/sektör ve teyitsiz pozitif haber yalnız sinyalde biliniyorsa gerekçelendirilir.

MFE/MAE mevcut günlük/5m OHLC hesaplarına **ek alan** olarak yazılır; başarı/temas sırası değiştirilmez. Yönle uyumlu, tam değerlendirme vadesinin favorable/adverse excursion'ıdır; portföy drawdown veya gerçekleşmiş işlem getirisi değildir. Stop öncesi MFE ve hedef öncesi MAE temas mumunu dışlar: aynı mumdaki sıra bilinmez ve muhafazakâr alt bilgi raporlanır. Temas yoksa ilgili pre-contact metrik `null`. Eksik OHLC `null`; eski tamamlanmış sonuçlarda olmayan metrikler sıfırla doldurulmaz. Hedefe yaklaşma MFE/hedef mesafesi oranıdır, 1'i aşabilir. ATR mesafesi ve kalite özetleri de minimum örnek/gün kapısına tabidir.

## Algoritma sağlığı

Public `algoritma_saglik.json` DAILY/INTRADAY altında yalnız aggregate veri taşır. Ana model sağlığı **LIVE** sinyallere dayanır; haber/makro event sonuçları ana model başarısına karıştırılmaz. Yeterli örnek/gün ve bilinen hedef/stop/veri kalitesi yoksa `YETERSIZ_VERI`.

Puan = 100 × (.40 başarı + .20 (1-stop) + .15 hedef + .15 (1-eksik veri) + .10 (1-stale)). Kanıtlı drift −15, confidence/teyit kalibrasyon uyarısı −5. Sınıflar ≥85 COK_IYI, ≥70 IYI, ≥50 NORMAL, altı ZAYIF. Bu bir tanısal sağlık göstergesidir, kârlılık garantisi değildir. Başarı/kısmi başarısızlık etiketleri mevcut sonuç motorunun tanımını korur.

Son 5/20/60 İstanbul hafta içi gün için başarı ve medyan eğrisi. Yakın 20 gün ile önceki ayrık 60 gün, minimum örnek/gün ve Wilson aralığı ayrışması + medyan bozulması sağlıyorsa MODEL_DRIFT. Yeterli veri yoksa “yok” değil “değerlendirilemedi”. Confidence 80+ / 60–70 ve teyit 3/4/5/6+ gruplarında yeterli örnekle başarı artmıyorsa uyarı; istatistiksel açık fark ayrı bayrak. Otomatik eşik/model değişimi yoktur. Rejim/sektör/haber türü hata oranları küçük örnekte gizlenir. Haber false-negative ölçümü yalnız kaydedilmiş negatif sinyalin geçerli yön sonucuyla sınırlıdır; haber gelmeyen/karar alınmayan tüm fırsatların counterfactual sonucu bilinmez.

Public `kombinasyon_performansi.json` ayrık kaynak/vade metriklerini taşır; bireysel hata kayıtları public olmaz. AI Öğrenme / Model Performansı ekranına kompakt Model Sağlığı, Ana/Shadow/Canlı başarı, kaynak sayıları, güçlü/zayıf kombinasyonlar, en sık hata, drift ve kalibrasyon uyarıları eklendi. Hisse detayı değişmedi.

## Config ve çalışma

- `MIN_COMBINATION_SAMPLES=50` (50–10000)
- `MIN_COMBINATION_DAYS=7` (7–250)
- `MAX_CRITERION_COMBINATIONS=64` (1–128)
- `PERFORMANCE_LIVE_RELIABILITY=1`
- `PERFORMANCE_BACKTEST_RELIABILITY=0.5`
- `PERFORMANCE_SHADOW_RELIABILITY=0.75` (0–1; LIVE en yüksek, sıfır olamaz)
- Mevcut `MIN_LEARNING_SAMPLES`, `MIN_LEARNING_DAYS`, `CONTROLLED_REPORT_INTERVAL` korunur.

Mevcut worker pending vade ve sınırlı sembol batch'ini kullanır. Yeni sonuç yoksa fingerprint ile tekrar hesaplama atlanır; değişiklikler mevcut rapor aralığında birikir (varsayılan saatte bir). Kombinasyon/health ağ çağrısı yapmaz, 805 hisseyi yeni bir provider taramasıyla dolaşmaz. Private/public dosyalar mevcut BIST_DATA_DIR helper'ı + lock + atomic write ile yazılır; iki mod birbirini ezmez. Cloud/web/worker başlatıcı, volume, push, VAPID ve /health değiştirilmedi. Gerçek Railway/iPhone doğrulaması bu yerel testlerin yerine geçmez.

Testler: `tests/test_karar_teshis.py`, `tests/test_algoritma_saglik_ui.cjs`; mevcut tam regresyon ayrıca çalıştırılır. Mock fiyat, geçici veri kökü; gerçek kullanıcı verisi/push/piyasa çağrısı yoktur.
