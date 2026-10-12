# Sinyal performansı: yalnız ölçüm

Mevcut tahmin hafızası ve `PerformansMotoru` source-of-truth olarak kalır.
`sinyal_performansi.py` fiyat istemez, tahmin/sonuç geçmişine yazmaz, karar,
skor, sıralama veya kalibrasyon girdisi değiştirmez. Mevcut performans raporu
üretilirken zaten bellekte bulunan native ve legacy kayıtlar analiz edilir.

Son rapor atomik olarak `BIST_DATA_DIR/public/sinyal_performansi.json`
(yerelde `webapp/data/sinyal_performansi.json`) üzerine yazılır. Önceki rapor
kopyaları biriktirilmez. `GET /api/signal-performance` ve `read_report()`
yalnızca bu küçük türetilmiş raporu okur; web isteğinde ham geçmiş parse
edilmez. İlk rapordan önce `PENDING_FIRST_REPORT` döner. Worker'ın mevcut
rapor zamanlaması kullanılır; yeni worker, tarama veya takip sistemi yoktur.
XIST vade sonu hesapları bellekte en fazla 16.384 anahtarla cache edilir.

## Veri kalitesi ve yön

1/3/5/10/20/60 işlem günü sonuçları ayrı kalır. Yalnız açık biçimde
`degerlendirme_tamamlandi=true` olan, geçerli baz/hedef/kapanış fiyatı,
baz fiyatla tutarlı getiri, XIST vade tarihi ve kapanıştan sonra gözlenmiş
zaman damgası bulunan sonuçlar istatistiklere girer. Pending, unverified,
malformed, eksik fiyat, gelecek özellik/sonuç veya analysis-only/shadow/
backtest kayıtları ayrı gerekçelerle sayılır. Hiçbiri silinmez veya onarılmaz.
Ham kayıt ID'si bulunmayan girdiler `malformed_records` sayacında ayrılır.

Mevcut AL/GUCLU_AL/AGRESIF_ALIS ve teyitli ASIRI_SATIM/tepki yükseliş;
SAT/GUCLU_SAT/AGRESIF_SATIS düşüş yönündedir. Kaydedilmiş açık karar önceliklidir.
YARIN_TOP10 mevcut yükseliş tahmini semantiğini kullanır. ASIRI_ALIM tek başına
SAT sayılmaz; açık yön yoksa UNKNOWN_DIRECTION olarak dışlanır.

Bu raporda başarı tanımı **yön getirisi > 0**'dır; mevcut hedef/stop tabanlı
başarı etiketini yeniden tanımlamaz. SAT için fiyat düşüşü pozitif yön getirisi
sayılır. Ham fiyat getirisi ayrıca raporlanır. MFE/MAE yalnızca kaydedilmiş
sonuç yönü bu yönle uyuşuyorsa kullanılır; ayrı örnek sayıları vardır.

Aynı sembol/zaman/sinyal/kaynak/güçlü-tepki gözlemi farklı import ID'leriyle
tekrarlanırsa bir kez sayılır. Aynı gözlemde çelişen özellik/sonuç veya başka
gözleme yeniden atanmış ID varsa güvenilir istatistikten çıkarılır.

## Özetler ve öğrenme örnekleri

Her sinyal ve vadede toplam, doğrulanmış completed, geçerli pending, dışlanma
nedenleri, yönsel pozitif/negatif/nötr sayıları, başarı oranı, ortalama/medyan,
en iyi/en kötü, standart sapma, MFE/MAE, kazanan/kaybeden ortalamaları,
payoff ratio ve profit factor bulunur. Kayıp örneği yoksa oranlar `null`
olur; sonsuz veya uydurma değer üretilmez. `total = completed + pending +
sum(excluded)`; duplicate'ler toplamı şişirmez.

Güven seviyeleri doğrulanmış sonuç sayısına dayanır:

- 0–29: INSUFFICIENT
- 30–99: LOW
- 100–299: MEDIUM
- 300+: HIGH

Bunlar örneklem yeterliliği etiketleridir; istatistiksel bağımsızlık,
nedensellik veya gelecek başarı garantisi değildir. İki başarılı örnekte
oran 1 olabilir ancak `sufficient=false`, `reliability=INSUFFICIENT` kalır.

Tahmin anındaki dondurulmuş RSI, MACD, hacim, SMA, mevcutsa VWAP/OBV/Bollinger,
momentum, teknik skor, güven ve fırsat bileşenleri üzerinden kriter
agregasyonları oluşturulur. Skor ölçeği 0–100'dür; yalnız dolu dilimler
üretilir (0–49, 50–59, 60–69, 70–79, 80–89, 90–100).
Son 7/30/90 gün ve ALL kohortları **tahmin zamanı** ile filtrelenir.
Uzun vadeli yeni tahminlerin sonuçları oluşmadan başarı paydasına alınmaz.

`clean_dataset(records, current)` doğrulanmış örnekleri iterator olarak verir.
Girdi özellikleri whitelist ile yalnız frozen kayıttan alınır; MFE/MAE/getiri
ayrı `outcome` bölümündedir. Sonradan canlı teknik veri okunmaz. Dataset başka
bir geçmiş dosyasına kopyalanmaz veya otomatik ağırlık öğrenmeye bağlanmaz.

Testler geçici kök, stub OHLC ve HTTP smoke kullanır; production verisine
bağlanmaz:

```sh
python -m unittest discover -s tests -p 'test_*.py'
```
