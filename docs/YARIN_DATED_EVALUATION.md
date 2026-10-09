# Yeni Yarın TOP10 tahminlerinin değerlendirme planı

Yalnız yeni günlük snapshot oluşturulurken `dated_evaluations.records` eklenir.
Eski arşiv okuması veya legacy dönüştürme bu alanı oluşturmaz; backfill yoktur.
Mevcut `tahmin` alanları korunur. Kayıtlar symbol/sinyal zamanı/referans fiyatı,
sinyalde dondurulan günlük hedef/stop, model+kalibrasyon+learning sürümü ve 1/3/5
BIST işlem günü tarihlerini taşır. Güncel fiyat veya genel `hedef1`/`stop` ile
eksik günlük seviyeler tamamlanmaz. Eksik/bozuk seviye veya bilinmeyen/gelecek
referans zamanı değerlendirmeyi engelleyen açık status ile korunur.

Aynı analiz günü+sembol+model sürümü aynı kimliği üretir; aynı kaydın tekrarı tek
metadata kaydıdır, çakışan aynı kimlik hata verir. Zaten kilitli gün tekrar
hesaplanmaz ve arşiv üzerine yazılmaz. Metadata yalnız primary TOP10 içindir;
karşılaştırma listeleri veya tüm adaylar tekrar kopyalanmaz. Snapshot başına ilave
metadata üst sınırı 16 KiB'dir. Yeni JSON geçmişi, WAL, cache veya indeks dosyası
oluşturulmaz; mevcut archive/current snapshot akışına kompakt metadata eklenir.

Europe/Istanbul ve mevcut XIST takvimi kullanılır. Açılış öncesi tahminde henüz
başlamamış bugünkü seans ilk değerlendirme seansıdır; kapanış sonrası tahminde
sonraki seanstır. Hafta sonu/tatil atlanır, yarım seans işlem günü olarak sayılır.
`evaluate_after` takvimdeki kapanışın 15 dakika sonrasıdır. `due()` read-only
planlama yardımcısıdır; henüz kapanmamış veya veri kalitesi yetersiz kayıt atlanır.
Sonuçlar tahmin metadata'sına geri yazılmaz. Bu aşama capture/planlamadır: yeni
fiyat çekme veya otomatik sonuç hesaplama worker'ı eklenmemiştir.

Geliştirme branch'i kararlı main tabanlıdır; önceki deneysel kalite filtreleri
branch'i korunmuştur, burada üretim seçim/puanlama formülü değiştirilmemiştir.
Production'a deploy/push yapılmaz; testler geçici kökler kullanır.

## Otomatik sonuç değerlendirme

Worker'ın mevcut performance turu sonunda `evaluate_round()` çağrılır. Yalnız bu
metadata'yı taşıyan READY tahminler değerlendirilir; legacy kayıtlar değişmez.
Sonuçlar runtime/yarin_dated_outcomes.sqlite3 içinde (prediction_id, horizon)
benzersiz anahtarıyla eklenir, güncellenmez. Büyük JSON geçmişi yeniden yazılmaz.
Kapanış getirisi ve pozitif kapanış isabeti, hedef/stop teması, günlük mumlarla
bilinebilen sıra ve referansa göre MAE hesaplanır. Aynı mumdaki iki temas UNKNOWN
olarak kalır; intraday sıra uydurulmaz. Komisyon dahil değildir.

Mevcut borsapy sağlayıcısı nominal referans/seviyelerle uyumlu unadjusted günlük
OHLC sağlar. Bölünme/sermaye işlemi içeren dönemlerde nominal getiri total return
olarak yorumlanmamalıdır. Tüm gerekli seanslar ve tutarlı OHLC zorunludur; eksik
veriyle sonuç yazılmaz. Her vade yalnız kendi seanslarını kullanır. Bir turda en
fazla 20 sembol okunur; her sembol bir kez alınır. Eksik/başarısız veriler 6 saat
sonra yeniden denenir, deferred sayısı raporlanır; sonraki semboller engellenmez.
Sağlayıcı hatası başarılı sonuçlar commit edildikten sonra yeniden yükseltilir.
Küçük SQLite transaction'ları kesintiden sonra mükerrer sonuç oluşmasını önler.
Hiçbir production bağlantısı, taşıma, silme veya deploy yapılmamıştır.
