# Ortak BIST AI karar ve ölçüm çekirdeği

On ikinci adımda sonuç ölçümü performans_motoru.py ile ortaklaştırıldı. Tam OHLC/işlem günü, immutable sonuç, minimum örnek ve öneri kuralları PERFORMANS_SETUP.md'de; aşağıdaki çekirdek kayıt/okuma modeli korunur.

`ai_karar_motoru.py` mevcut teknik analizleri ve `haber_etki_motoru` yardımcılarını kullanır. Yeni veri sağlayıcısı, teknik tarama veya ikinci öğrenme geçmişi oluşturmaz. Ortak skor bir bağlamdır: Gün İçi/Yarın TOP10 seçim puanlarını ve immutable tahminleri değiştirmez. Kullanıcı seviyeleri, fiyat alarmı ve push kayıtlarına yazmaz.

## Skor ve açıklama

Başlangıç ağırlıkları: teknik %70, haber %12, makro %6, bağımsız sektör %4, fiyat teyidi %3, benzer geçmiş başarı %3, piyasa rejimi %2. Dosya ilk kullanımda runtime `ai_agirliklari.json` olarak oluşturulur. Dosyadaki ağırlıklar kontrollü normalize edilir; teknik .55–.80, haber .05–.18, makro 0–.10, sektör 0–.08, fiyat teyidi 0–.06, geçmiş/rejim 0–.05 sınırlarında tutulur. JSON’daki `esikler` güvenli sıralama içinde ayarlanabilir: varsayılan GUCLU_AL 82, AL 70, SAT 35, GUCLU_SAT 20; arası IZLE.

Skor `50 + Σ(grup_değeri × ağırlık)` olarak 0–100 aralığında üretilir. Teknik grup mevcut teknik puanı veya mevcut AL/SAT puan farkının merkezlenmiş halini kullanır; haber/makro/sektör -10..10, fiyat teyidi -4..4, rejim -5..5 girdileri ortak -50..50 katkı ölçeğine alınır. Diğer gruplar boşsa nötr kalır; eksik veri ağırlığı habere kaydırılmaz. Bu nedenle teknik skorun yeni adı değildir ve tek bir olay teknik gövdeyi ezemez.

RSI, MACD/signal/histogram, trend/SMA, hacim, varsa VWAP/OBV/Bollinger, destek/direnç, R/R ve gün içi sinyal durumu kayıtlı girdilerdir. Bu göstergelerin mevcut teknik puana dahil katkısı ikinci kez eklenmez: `indikator_katkilari` hangi gruba ait olduklarını, ham değerlerini ve ayrı ek puanın sıfır olduğunu açıkça kaydeder. Mevcut `karar_nedenleri`/`nedenler` korunur. Grup katkıları sayısal; haberlerin tekil katkıları, referans fiyatı, yaşı, sönümü ve teyit katsayısı ayrıca kayıtlıdır. Pozitif/negatif nedenler katkı büyüklüğüne göre sıralıdır; riskler ayrı gösterilebilir. Confidence ampirik kazanma olasılığı değildir; veri kapsamı/tazeliği göstergesidir.

## Haber, makro ve fiyat teyidi

Private canonical haber ledger’ı tercih edilir; yoksa mevcut haber geçmişi okunur. Canonical ID bir değerlendirmede yalnızca bir kez katkı verir. En yeni beş olayın her biri gerçek yayın/keşif yaşına göre mevcut `haber_etki_sonumleme` ile 180 dakika yarılanma süresinde sönümlenir. Zamanı olmayan/gelecekteki haber taze sayılmaz ve katkı vermez. KAP ve şirket sitesi aynı canonical olayın kaynaklarıdır; ayrı puan değildir.

Mevcut `bist_bot.py` içindeki üç `haber_dakika=0` çağrısı gerçek kayıt yaşını okuyan `haber_yasi_getir` ile değiştirildi. Bu eski uyumluluk yolu son beş kaydın en yeni geçerli yaşını kullanır; ortak çekirdek her olayı ayrı sönümler. Teknik seçimin diğer kriterleri değiştirilmedi.

Teyit günlük yüzde değişimi haber sonrası getiriymiş gibi kullanmaz. Haber anında bilinen referans fiyat varsa onu kullanır. Yoksa ilk AI gözlem fiyatı private `ai_fiyat_teyit.json` içinde dondurulur; ancak sonraki gözlem teyit edebilir ve kayıtta `referans_turu=ILK_AI_GOZLEMI` etiketi vardır. Bu, haberin tam yayın fiyatı değildir. Fiyat referansın üzerine çıkmalı ve hacim oranı en az %100 olmalıdır. Pozitif haber teyitsizse katkısı %35’e iner; hacim tek başına pozitif fiyat teyidi vermez. Negatif haber bu indirimle gizlenmez. VWAP/OBV mevcut teyit yardımcı fonksiyonuna aktarılır.

Mevcut makro yazıcı sektör alanına aynı makro olayını kopyalar. Yeni `event_id`/`sektor_event_id` metadata’sı bu ortak kökeni belirtir; çekirdek aynı olayı makro ve sektör üzerinden iki kez saymaz. Eski eşit/kökeni belirsiz kopyalarda sektör katkısı konservatif biçimde sıfırlanır. Bağımsız sektör olayı farklı ID ile desteklenir. Haber canonical ID’siyle çakışan makro olayı da tekrar sayılmaz. Makro bağlamı 24 saat yarılanma süresinde sönümlenir. Ortak çekirdek hedef/stop üretmez veya değiştirmez; mevcut negatif etki için hedef=min/eski, stop=max/eski koruması yerinde kalır.

## Tazelik ve ortak okuma

Teknik zaman 10–20 dakika gecikmişse confidence ×.70, 20 dakikadan eskiyse ×.35, zaman bilinmiyorsa ×.50 uygulanır. Eksik teknik skor confidence’ı en fazla 20’ye indirir. Dosya zamanına geri düşülürse ayrıca ×.80 ve `HISSE_BAZLI_ZAMAN_EKSIK` kaydedilir. Confidence <50 veya ağır negatif haber/makro olduğunda AL/GUCLU_AL kararı IZLE’ye düşer. Eksik haber/makro katkı vermeden motor çalışmaya devam eder.

Ortak public dosya `ai_hisse_ozetleri.json`: `{surum, updated_at, hisseler: {SEMBOL: özet}}`. Özet: ai_score, karar, confidence, gerekçe, neden dizileri, risk_flags, katkilar, veri_tazeligi, teknik kriterler, haber detayları, rejim, sektör, ağırlıklar, sinyal_id ve İstanbul offset’li zamanlar. Kullanıcı kimliği/alarmlar/subscription/secrets içermez.

`ai_ozet_oku(sembol)` salt okur; hesaplama veya yeni sinyal yazmaz. `GET /api/stocks/SEMBOL` mevcut manuel/otomatik/alarm yanıtına `ai_ozet` ekler (yoksa null). Hisse Ara, TOP10, Favoriler ve ilerideki AI Asistan aynı public JSON veya bu ortak okuma yolunu kullanabilir. Bu adımda bu ekranların özel skorları veya görsel tasarımları değiştirilmedi.

## Öğrenme ve ölçüm

Yeni sinyaller **mevcut** `ai_ogrenme_gecmisi.json` dosyasının `kayitlar` listesine `model=ORTAK_AI` etiketiyle eklenir. Eski GUN_ICI kayıtları korunur; eski yazıcılar ve çekirdek aynı flock/atomic yazımı kullanır. Bozuk geçmiş sessizce sıfırlanmaz. Sinyal kimliği sembol, teknik veri zamanının mevcut öğrenme yapısına uygun beş dakikalık dilimi, karar, canonical olaylar ve rejimden üretilir; aynı girdinin tekrarı veya eşzamanlı iki değerlendirme ikinci kayıt üretmez. İlk sinyal fiyatı, confidence, katkılar, nedenler ve 1/3/5/10/20/60 günlük sonuç alanları saklanır. Seans dışı/yetersiz güvenli kayıtlar REFERANS’tır ve öğrenmeye girmez.

`ai_sonuclari_guncelle(sembol, kapanislar)` tamamlanmış, tarihli işlem seansı kapanışları alır (`timestamp`, `close`). Sinyal gününden sonraki 1/3/5/10/20/60. seansların getirisini sinyal fiyatından ölçer; gelecekteki gözlemleri ve aynı günü dışlar, aynı günün tekrarını tek sayar. Yazılmış sonuçlar donuktur. Çağıran, mevcut provider/history’den tamamlanmış borsa seanslarını sağlamalıdır: bu adım ayrı otomatik geçmiş fiyat taraması kurmaz. `contribution_performance()` beş günlük katkı/yön uyumunu betimsel raporlar; nedensellik veya otomatik optimizasyon iddiası yoktur.

Benzer geçmiş katkısı aynı sembol/sektör ve ortak modelde aynı rejimdeki gerçek sonuçlardan gelir. En az 30 tamamlanmış uygun örnek olmadan sıfırdır. Sonuç gözlem zamanı değerlendirme anından sonraysa kullanılamaz.

`LEARNING_ENABLED=false` varsayılan. Otomatik optimizer veya kaynak kodu düzenleme yoktur. İstenirse açık `AIKararMotoru.update_weights(proposed)` çağrısı yalnızca `LEARNING_ENABLED=true` ile çalışır. Her grubun min/max sınırı ve **gün başlangıcına göre toplam .005 günlük değişim sınırı** vardır; art arda çağrı bu sınırı büyütemez. Eski GUN_ICI öğrenme raporu ortak ağırlık dosyasını değiştiremez; bu çekirdek eski gösterge ağırlıklarını otomatik içeri aktarmıyor.

## Worker, yollar ve test

`ai_hisse_guncelle`, `ai_batch_guncelle` tek tur fonksiyonlarıdır; yalnızca hazır JSON/analiz girdilerini okur. Worker öncelikli analiz, kontrollü tam tarama batch’i ve TOP10 görevlerinden sonra ortak bağlamı günceller. Batch sembol hatalarını ayırır; genel AI hata sınıfı worker’a sonuç olarak döner, diğer görevleri durdurmaz. Bağımsız 7/24 ikinci worker eklenmedi.

`BIST_DATA_DIR` varsa public özet root/public; ağırlıklar, teyit state ve mevcut öğrenme geçmişi root/runtime içindedir. Yerelde mevcut legacy öğrenme geçmişi yolu korunur (web sunucusu static erişimi reddeder), yeni private state `.local/runtime` altında kalır. User-data ve arşivler değişmez. Web ve worker aynı environment ile aynı dosyaları görür. Gerçek provider’a deploy yapılmadı.

Testler mock analiz/haber/kapanış kullanır: pozitif/negatif teknik/haber/makro, bağımsız sektör, sönümleme ve yayın zamanı, fiyat/hacim teyidi, canonical dedup, tazelik/eksik veri, normalize/min/max/günlük öğrenme sınırları, learning disabled, açıklamalar, eşzamanlı sinyal/legacy yazımı, batch hata izolasyonu, sonuç vadesi/future-leak guard, eski kayıt ve snapshot/alarm/push koruması, worker hata izolasyonu, salt okuma ve HTTP özet erişimi.
# Ortak piyasa bağlamı (on beşinci adım)

Normal batch kararlarında basit BIST100 yüzde değişim proxy'si yerine ortak `piyasa_durumu.json` kullanılır. Rejim, breadth ve fiyat tabanlı sektör relatif güç ayrı, sınırlı katkılardır; teknik/haber/makro ağırlık öğrenimiyle karıştırılmaz. Bağlam tek başına AL/SAT üretmez. Kullanılan context geçmişte dondurulur. Puan zinciri, config, minimum coverage ve stale politikası PIYASA_BAGLAMI.md'de.
