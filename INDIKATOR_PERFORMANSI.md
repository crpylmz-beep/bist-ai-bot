# Frozen indikatör performansı

Mevcut sinyal performansı katmanı genişletildi; ikinci sonuç/takip motoru yok.
Yeni günlük/ortak AI tahminleri yalnız mevcut analiz alanlarını
`indicator_snapshot` içinde tahmin anında kopyalar. Eski ham kayıtlar ve
completed sonuçlar değiştirilmez. Eski kayıtta açıkça bulunan frozen alanlar
kullanılır; eksik alanlar `unavailable` sayacına gider, canlı veriyle doldurulmaz.
Yeni snapshot varsa sonraki raw özellikten önce snapshot kullanılır.

RSI: 0–29, 30–39, 40–49, 50–59, 60–69, 70–100.
MACD: işaret, signal ilişkisi; histogram: işaret ve yalnız iki kayıtlı
histogram değeri varsa iyileşme/kötüleşme.
Hacim oranı mevcut yüzde ölçeğindedir: <80, 80–119, 120–149, 150–199, 200+.
SMA: fiyat/SMA20, fiyat/SMA50, SMA20/SMA50; mevcutsa EMA9/EMA21.
VWAP, OBV ve Bollinger raw frozen alanlardan veya status=OK olan frozen
standart gösterge grubundan okunur. Sıkışma/kırılım booleans mevcutsa ölçülür.
ATR14/fiyat yüzdesi <2, 2–4 ve 4+ gruplarındadır; ATR yeniden hesaplanmaz.
Mevcut nihai karar motoru altı teknik teyit kullanır. Gerçek sayılar 0/6–6/6
ve teyit yüzdesi gruplarıyla analiz edilir; kaydedilmemiş sayı üretilmez.

Yalnız altı sabit kombinasyon vardır: RSI+MACD, MACD+hacim, RSI+hacim,
VWAP+OBV, trend+hacim, RSI+MACD+hacim. Tüm bileşenlerin frozen verisi varsa
CONFIRMED veya NOT_CONFIRMED grubu üretilir. Kombinasyon gücü bir yatırım
kuralı değildir; kontrol grubu karşılaştırması ve gözlemsel ölçümdür.

Aynı Stats, quality, direction, reliability, duplicate ve XIST mantığı
kullanılır. Altı vade; ALL veya gerçek sinyal türü; son 7/30/90 gün ve ALL
kohortları ayrıdır. 30'dan az verified örnek INSUFFICIENT; 30–99 LOW,
100–299 MEDIUM, 300+ HIGH. Pending başarı paydasına alınmaz. MFE/MAE ayrı
örnek sayılarıyla raporlanır. Eksik özellik sayacı tüm girdi kohortunu kapsar.

Yeni çıktı mevcut yeniden üretilebilir `sinyal_performansi.json` cache'inin
`indicator_analysis` alanındadır. Önceki dosyalar biriktirilmez; atomik olarak
üstüne yazılır. Worker'ın mevcut rapor zamanı ve zaten yüklenmiş ham geçmiş
kullanılır. Cache bozuk/kayıpsa sonraki rapor üretimi ham veriden yeniden yazar.
API ham geçmiş parse etmez, provider çağırmaz, ağırlık/puan/rank değiştirmez.
Temiz dataset'in özelliklerinde frozen indicator_conditions bulunur;
MFE/MAE yalnız outcome olarak kalır.

`GET /api/indicator-performance` filtreleri:

- `indicator`: RSI, MACD_SIGN, MACD_SIGNAL, HIST_SIGN, HIST_TREND, VOLUME,
  PRICE_SMA20, PRICE_SMA50, SMA_TREND, EMA_TREND, VWAP, OBV, BOLLINGER,
  BOLL_SQUEEZE, BOLL_BREAKOUT, ATR, MOMENTUM, CONFIRMATIONS,
  CONFIRMATION_COUNT veya tanımlı COMBO_* isimleri.
- `condition`: ilgili indikatörün tanımlı koşul etiketi.
- `signal_type`: ALL veya mevcut AL/SAT/AGRESIF_*/ASIRI_*/YARIN_TOP10 sınıfı.
- `horizon`: 1/3/5/10/20/60.
- `period`: 7/30/90/ALL (tahmin zamanı baz alınır).

Bilinmeyen, boş, tekrarlı veya uyumsuz filtreler 400 döner. Rapor oluşmadan
PENDING_FIRST_REPORT, geçerli ama verisiz sorguda boş rows döner.
`/api/signal-performance` mevcut alanları ve davranışı korunur.

Örnek:

```
/api/indicator-performance?indicator=RSI&condition=30-39&signal_type=AL&horizon=3&period=90
```
