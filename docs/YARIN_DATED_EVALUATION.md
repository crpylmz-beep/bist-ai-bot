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
