# Bağımsız Gün İçi TOP10 performansı

`gun_ici_performans.py` Gün İçi sinyallerini kendi veri deposunda ölçer. Yarın ağırlıkları, sonuçları, öğrenme geçmişi ve immutable arşivlerine yazmaz. Yalnız ortak saf istatistik yardımcıları (medyan, trimmed ortalama, Wilson güven aralığı ve kriter karşılaştırması), mevcut JSON kilit/atomic yazım ve merkezi yollar yeniden kullanılır. Eski ortak AI akışı korunur; yeni Gün İçi öğrenme onun dosyalarına bağlı değildir.

## Mevcut analiz ve veri

`gun_ici_top10_tara()` Stream'den 5 dakikalık mumları alır; eksik sembollerde mevcut `borsapy.Ticker.history` yoluna döner. `gun_ici_analiz_hesapla()` aynı teknik formülleri kullanır; açık/gelecek 5 dakikalık mumlar göstergelere dahil edilmez. Gün İçi ham puan açılış değişimi, dipten toparlanma, zirveye mesafe, RSI, MACD, hacim, momentum ve kırılım katkılarını mevcut haber birleştirme ile hesaplar. EMA9/21, VWAP, OBV ve diğer hazır değerler ikinci kez hesaplanmaz.

Normal analiz aday eşiği 45 ve mevcut sert risk filtreleri korunur. Learning kapalıyken ham puan, hacim ve momentum sıralama anahtarı değişmez. TOP10 ve tüm Gün İçi web çıktıları artık atomic yazılır. Sinyal zamanı/yaşı İstanbul saatindedir.

## Sinyal kimliği ve kayıt

Sinyalin kaynak mumu kapanmış, aynı seans içinde ve en fazla 15 dakika yaşında olmalıdır. Kimlik sembol+kaynak mum zamanı+dondurulmuş analiz özeti hash'idir. Aynı kaynak mumuyla tekrar çağrı yeni sinyal oluşturmaz. Son sinyale göre karar değişimi, fiyatın en az %1 değişimi, skorun en az 5 puan değişimi, hedef/stop'un en az %1 değişimi veya önceki sinyalin sonlanması anlamlı yeni sinyal sayılır. Yeni gün yeni kayıt açar.

Kayıt giriş fiyatı, sinyal/kaynak zamanı, yaş, ham skor, karar, AL alt/üst, hedef, stop, sektör, rejim, ai_score, confidence, ilk sıra ve model sürümünü saklar. `analiz` kaynak satırın dondurulmuş kopyasıdır: VWAP/hacim/EMA/RSI/MACD/OBV/momentum/haber/makro ve varsa Bollinger burada korunur. Mevcut Gün İçi analiz Bollinger/rejim üretmiyorsa alan bilinmeyen kalır; hayali değer, nötr puan veya yeni gösterge üretilmez. HABER mevcut haber/KAP etkisini birlikte temsil eder.

Durumlar YENI_AL, AL_DEVAM, ZAYIFLIYOR, SAT_DONDU, HEDEF, STOP, SONLANDI desteklenir. Yaş ve takip durumu güncellenebilir; giriş/analiz/seviyeler değişmez. Tamamlanan vade sonucu yeniden yazılmaz.

## Vadeler, temas ve başarı

Vadeler 5/15/30/60 dakika ve 18:10 seans sonudur; ana öğrenme metriği 60 dakikadır. Mum timestamp'i başlangıç zamanı kabul edilir. Sinyal 11:00:13'teyse ilk kullanılabilen tam mum 11:05–11:10'dur: nominal 5 dakika sonucu 11:10'da tamamlanır. `kullanim_suresi_dk` gerçek süreyi, `sonuc_zamani` gerçek son noktayı gösterir. Vadeler seans sonuyla sınırlanır; geceye taşınmaz.

Yalnız sinyalden sonra başlayan ve tamamen kapanmış 5 dakikalık OHLC kullanılır. Eksik beklenen mum varsa daha sonraki bara kaydırılmaz: VERI_YETERSIZ kalır. Sağlayıcı günlük veya yetersiz çözünürlük döndürürse intraday sonuç uydurulmaz. Kaynak timestamp, tutarlı OHLC ve kapanış kontrol edilir; aynı mumda hedef+stop ilk teması BELIRSIZ'dir ve eğitimden çıkarılır.

AL için stop < giriş < hedef ve risk/getiri ≥1 gerekir. Önce stop STOP, önce hedef BASARILI; hedef yokken getiri başlangıç riskinin en az yarısına ulaştıysa KISMEN_BASARILI, aksi BASARISIZ. Dolayısıyla küçük pozitif getiri tek başına başarı değildir. SAT/IZLE kayıtları fiyat hareketi referansıdır; long seviyeleriyle varsayımsal short başarısı üretilmez. Her vadede getiri, maksimum yükseliş/düşüş, hedef/stop teması, ilk temas, risk/getiri ve kullanım süresi saklanır.

## Bağımsız örnek, kriterler ve shadow

Eğitim için her sembol/günde ilk AL sinyali önceden seçilir; eksik/başarısız ilk kayıt daha sonraki kazananla değiştirilmez. Örnekler sonuç durumuna göre seçilmez. Her kriterin var/yok grubunda en az 40 hisse/gün örneği, 5 farklı işlem günü, sıfırı dışlayan %95 Wilson fark aralığı ve en az 0.25 puan yönlü medyan getiri farkı gerekir. `GUN_ICI_MIN_LEARNING_SAMPLES` 40 altına inemez. Medyan ve %10 trimmed ortalama tek uç gözleme karşı korunur.

VWAP, HACIM, EMA, RSI, MACD, OBV, BOLLINGER, MOMENTUM, KIRILIM, HABER, MAKRO, SEKTOR, REJIM ayrı karşılaştırılır. Sektör ve rejim bazlı sonuç özetleri de rapora eklenir; bilinmeyen göstergeler var/yok sayılmaz.

`GUN_ICI_LEARNING_ENABLED=false` varsayılandır ve ortak `LEARNING_ENABLED` ayarından bağımsızdır. Kapalıyken sonuç/öneri/shadow hesaplanır, ana puan değişmez. Açıldığında yalnız güvenli kriterler uygulanır. Düzeltme ±3 puan, katsayı başlangıcın 0.5–1.5 katı, günlük değişim en fazla 0.005 ve öneri adımı 0.0025'tir. Model günde bir yenilenir, sürümleri saklanır. Negatif haber/makro/sektör veya RSI≥70 pozitif öğrenme bonusu alamaz; elenmiş adaylar geri alınmaz, hedef/stop değiştirilmez. Otomatik aktivasyon yoktur.

Satırlarda `gun_ici_ham_puan`, `gun_ici_final_puan`, `gun_ici_shadow_puan`, `gun_ici_kalibrasyon_duzeltmesi`, `gun_ici_model_version` hazırdır. Ana ve shadow TOP10 üyelik/sıralamaları sonuç görülmeden kaydedilir; shadow ana liste dışından aday seçebilir. Tamamlanan liste çiftlerinin TOP3/TOP5/TOP10 ve ortalama sonuçları karşılaştırılır. Yeniden kullanılan bir sinyalin değerlendirme vadesi yeni liste zamanında bitmişse o listeye geriye dönük performans atfedilmez.

Günlük rapor sembol/gün ilk ana liste sinyalinden pozitif aday, hedef/stop, ortalama/medyan/trimmed getiri, TOP3/5/10, en iyi/kötü ve skor-getiri korelasyonunu üretir. Öğrenme örneklerinden farklı olarak referans/ambiguous kayıtların gerçek fiyat hareketleri raporda görülebilir. Bu bir gözlemsel ölçümdür; nedensellik veya gerçek piyasa başarısı iddiası değildir.

## Depolama ve worker

`BIST_DATA_DIR` altında:

- `runtime/gun_ici_sonuclar.json`: private sinyaller, immutable vade sonuçları ve dondurulmuş liste üyelikleri.
- `runtime/gun_ici_mumlar.json`: mevcut Stream'den biriken kapanmış mum cache'i; sembol başına son 7 takvim günü.
- `runtime/gun_ici_agirliklari.json`: private bağımsız ağırlıklar, kanıt ve sürümler.
- `public/gun_ici_performans.json`: güvenli sonuç/kriter/shadow raporu.
- `public/gun_ici_onerilen_agirliklar.json`: güvenli öneri raporu.

Environment yoksa runtime `.local/runtime`, public `webapp/data` olarak korunur. Yeni dosyalar gerektiğinde oluşturulur, gerçek kullanıcı verisi taşınmaz. Yazımlar atomic replace/fsync ve ortak dosya kilitleri kullanır. Fiyat çağrısı ana sonuç kilidini tutmaz; güncellenen kayıt merge edilir.

`bekleyen_gun_ici_sonuclari_guncelle()` tek turdur. Önce mevcut tarama mum cache'i kullanılır; yetersizse mevcut borsapy provider'ı `history(period='5d', interval='5m')` çağırılır. Sembol başına turda tek çağrı; `GUN_ICI_PERFORMANCE_BATCH_SIZE=10` (1–25), sembol başına en fazla 10 açık kayıt. Hata diğer sembolleri durdurmaz; eksik/hatalı kayıt 5 dakika sonra yeniden denenir. 5 takvim gününden eski, provider kapsamı yetersiz sinyal açıkça VERI_YETERSIZ ile sonlandırılır.

Ana motorda ayrı `intraday_performance` görevi varsayılan 300 saniyedir (`INTRADAY_PERFORMANCE_INTERVAL_SECONDS`). Teknik tarama/Yarın performansı lane'ine bağlanmaz; executor içinde ana scheduler'ı bloklamadan çalışır. Bir görev halen çalışıyorsa ikinci tur başlatılmaz. Provider gecikmesi o görev slotunu tutabilir; provider erişim/timeout davranışı deployment öncesi doğrulanmalıdır. Resmi tatil/yarım gün takvimi otomatik bağlı değildir; mevcut hafta içi/seans sınırı kullanılır.

## Test

`python -m unittest discover -s tests -q`; yeni sinyal/duplicate/değişim, hedef-stop sırası/ambiguous, gerçek süre/seans sonu, eksik/future mum, stock/day örnek seçimi, minimum/güven/outlier, learning/shadow, limit/sürüm, cache/provider/batch, byte düzeyinde Yarın izolasyonu, bağımsız scheduler ve HTTP raporu test edilir. Fiyat/saat sağlayıcısı fake; tüm dosyalar geçici volume altındadır. Cloud deploy veya büyük UI eklenmez.
