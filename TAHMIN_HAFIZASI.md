# Tahmin hafızası ve işlem günü sonuçları

Mevcut `tahminleri_kaydet()` ve `PerformansMotoru` birlikte kullanılır.
İkinci bir tahmin geçmişi oluşturulmaz. Cloud'da tahminler
`BIST_DATA_DIR/runtime/tahmin_gecmisi.json` içinde, yerel eski yapıdaysa
`webapp/data/tahmin_gecmisi.json` içinde kalır. Mevcut kayıtlar silinmez.

Worker, başarılı küçük tarama batch'lerindeki anlamlı sinyalleri kaydeder.
`NOTR` sonuçlar yalnızca mevcut AL/SAT kararı, güçlü tepki veya mevcut
TOP10 seçimi varsa takip edilir. Kısmi batch için TOP10 yeniden sıralanmaz.
Ortak AI kaydı da yeni IZLE/BEKLE sonuçlarıyla büyütülmez; analiz cevabı değişmez.

Gün + sembol + sinyal + kaynak + güçlü tepki durumu duplicate anahtarıdır.
Aynı gün aynı sinyalin yeni fiyatı eski tahmin fiyatının üzerine yazılmaz.
Farklı kaynak veya sinyal sınıfı ayrı kaydedilir. Kilit ve atomic JSON yazımı
eşzamanlı worker güncellemelerinde veri kaybını önler. Bozuk geçmiş dosyası
boş geçmişle değiştirilmez. Worker'da yazım hatası gerçek exception olarak
mevcut hata sınıflandırmasına iletilir.

Her kaydın `takip` alanında 1/3/5/10/20/60 işlem günü için hedef tarih ve
PENDING/COMPLETED durumu bulunur. Mevcut XIST işlem takvimi ve İstanbul
saat dilimi kullanılır; hafta sonları ve borsa tatilleri sayılmaz.
Sonuç, tahmin tarihinden sonraki ilgili seansın kapanışından sonra hesaplanır.
`sonuc_1g` ... `sonuc_60g` alanları tahmin fiyatını baz alır; yalnızca o
vadenin son tarihine kadar olan veriyi kullanır. Eksik seans/OHLC/baz fiyat
sonucu tamamlamaz; altı saatlik mevcut retry state ile tekrar denenir.
Restart sonrası kayıtlar ve retry state aynı kalıcı kökten yüklenir.

MFE/MAE, mevcut yön duyarlı hesapla pencerenin high/low değerlerinden
üretilir. Eksik veride sahte sıfır üretilmez. Aynı mum içinde hedef ve stop
görülürse sıra belirsiz olarak korunur. Tamamlanan vade tekrar hesaplanmaz.
Hedef seans tarihi ile gerçek değerlendirme tarihi ayrı tutulur.

Eski tamamlanmış sonuçlar değiştirilmez. Eski sonuçlarda açık doğrulama
bayrağı bulunmuyorsa `legacy_unverified` etiketiyle güvenilir özet dışında
tutulur. Eski nötr kayıtlar silinmez, yeni takibe alınmaz.

`performans_ozeti.json` içinde `tahmin_hafizasi` vade, sinyal ve kaynak
özetlerini; `yarin_top10_vadeler` mevcut frozen TOP10'un altı vadesini verir.
Legacy kayıtlar AI öğrenme geçmişine kopyalanmaz ve kalibrasyon girdilerine
eklenmez. Yatırım skorları, sıralama, ağırlıklar ve mevcut pozitif aday
1/2/3/5/10 rapor sözleşmesi değiştirilmez.

Testler gerçek kullanıcı verisi veya piyasa servisi yerine geçici klasör ve
sabit OHLC sağlayıcı kullanır:

```sh
python -m unittest discover -s tests -p 'test_*.py'
```
