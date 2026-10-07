# Ortak nihai karar — 17. adım

Mevcut `ai_karar_motoru.evaluate` geliştirildi. Yeni bir provider, ayrı karar motoru veya worker görevi yoktur. `FINAL_DECISION_V1` mevcut katkı puanını yeniden puanlamadan teyit ve güvenlik politikası uygular.

## Mevcut akış ve uyumluluk

Günlük teknik karar, Gün İçi teknik karar, haber AI yorumu ve Yarın sıralaması önceden ayrı AL/SAT etiketleri üretebiliyordu. Bunlar farklı zaman ufukları ve amaçlara aittir. Artık hepsi aynı nihai karar politikasına analizlerini verir; Gün İçi kısa zaman dilimini korur. Günlük ve kısa veri aynı hesapta birleştirilmez.

Nihai sözleşme `nihai_karar` nesnesindedir: `GUCLU_AL`, `AL`, `BEKLE`, `SAT`, `GUCLU_SAT`. Eski ortak AI `karar` alanında `BEKLE` karşılığı `IZLE` kalır; yönlü kararlar nihai kararla aynıdır. Eski teknik seviye/puan API alanları korunur. UI bunları Teknik karar ve Analiz AI puanı diye etiketler; ana karar kartında yeni sözleşme kullanılır.

`GET /api/stocks/SEMBOL?model=GUNLUK|GUN_ICI` mevcut cevabına `nihai_karar` ekler. Aynı zaman dilimindeki daha yeni ortak worker sonucu tercih edilir; böylece yeni kritik KAP/haber riski eski teknik AL kartının arkasında kalmaz. Başka zaman dilimindeki sonuç aynı karta karıştırılmaz. GET hesap yapmaz ve geçmişe yazmaz; sadece kaydedilmiş kararı okur. Okumada eski kayıt BEKLE/düşük güven gösterilebilir, dondurulmuş kaynak değişmez.

## Puan, güven ve teyit

- Karar puanı mevcut `ai_score` katkı hesabıdır: teknik, haber/KAP, makro, sektör, fiyat teyidi, geçmiş ve piyasa. Standart göstergelere ikinci puan verilmez. Mevcut ağırlıklar ve puan eşikleri korunur (güçlü AL 82, AL 70, SAT 35, güçlü SAT 20; doğrulanmış mevcut config kullanılır).
- Confidence veri kapsamı, zaman, haber/makro/piyasa kapsamı ve geçmiş örneklerinden gelir. Yüksek karar puanı düşük confidence'ı telafi etmez. Kalite gerekçeleri ayrıca Türkçe gösterilir.
- Trend, momentum, hacim, fiyat konumu, OBV, Bollinger altı teknik kategoridir. Risk/getiri, piyasa/sektör ve haber ayrı bağlam/güvenlik kategorileridir. Teyit sayısı altı teknik kategori üzerinden verilir. Günlük AL en az üç, Gün İçi AL dört olumlu teknik kategori ve trend veya momentum teyidi ister; teknik güç ≥65, confidence ≥50 ve yeterli risk/getiri şarttır.
- Güçlü AL en az beş teknik teyit, teknik güç ≥85, trend+momentum+hacim birlikte olumlu ister. Güçlü düşüş + breadth <-20 halinde eşik altı teyittir. Makro/sektör/piyasa katkısı tek başına AL/SAT eşiğini geçiremez: bağlam puanı çıkarılmış çekirdek puan da yön eşiğini sağlamalıdır.
- SAT en az iki olumsuz teknik kategori, trend veya momentum bozulması ve confidence ≥50 ister. RSI yüksekliği tek başına SAT değildir. Güçlü SAT en az dört olumsuz teyit, teknik güç ≤25 ve güçlü satış puanı ister. Stop teması veya kritik haber satış değerlendirmesini destekleyebilir; kalite ve çelişki kurallarını kaldırmaz.
- İki olumlu/iki olumsuz teknik kategori veya VWAP üstü + MACD/OBV negatif çelişkisi BEKLE/düşük güven üretir. Teyit, yön puanı veya kalite yetersizse BEKLE olur.

## Güvenlik

Günlük düşüş ≤-%7, aşırı yükseliş (>Gün İçi %5 / günlük %4), kritik negatif haber (ham ≤-5), fiyat ≤stop, düşük/bilinmeyen risk/getiri, aşırı alım, eski/eksik veri AL'ı engeller. Kritik negatif haber güveni en fazla 49 yapar; otomatik SAT zorlanmaz. Eski/bilinmeyen teknik zaman güveni en fazla 35, veri eksikliği 20 yapar.

Aşırı satım tek başına AL değildir. Tepki için dipten toparlanma, pozitif son mum, hacim, histogram iyileşmesi ve RSI yükselişi birlikte aranır; kalan AL kuralları yine geçerlidir. Mevcut tepki seçim fonksiyonları değişmedi. ATR ve hacimli kırılım seviyeleri açıklamada kullanılır; ek puan verilmez.

## Kayıt ve performans

Gün İçi sinyal geçmişi, Yarın tarih arşivi ve ortak AI özel geçmişi `nihai_karar` nesnesini saklar. İçinde karar, puan, confidence, teknik güç, risk puanı, teyit sayısı/toplamı, ana neden/risk, Türkçe gerekçeler, kriter bayrakları, sayısal girdi snapshot'ı, veri/karar zamanı ve model sürümü vardır. Ortak AI kimliği model sürümünü de içerir. Eski arşivler geriye dönük doldurulmaz; aynı gün Yarın arşivi overwrite edilmez.

Mevcut public performans özetlerinde `nihai_karar_performansi` karar, confidence (0–49/50–69/70–100), teyit sayısı kırılımlarını ayrı ölçer. Gün İçi 5/15/30/60 dakika + SEANS, günlük 1/3/5/10/20/60 işlem günü kullanır. Tamamlanmış, kaliteli ve rapor anında bilinen sonuçlar gerekir. Gelecekte kaydedilmiş snapshot/sonuçlar sayılmaz. Otomatik karar eşiği değişimi yoktur; yeni sözleşmede learning kapalıdır. Mevcut opt-in öğrenme altyapısı değiştirilmedi.

## Lookahead ve işletim

Gelecek quote kabul edilmez; standart göstergelerin kendi asof/data_time kalite kontrolleri kullanılır. Haber yayın/ilk görülme/güncelleme/analiz zamanlarından biri gelecekteyse olay dışlanır; gelecekteki makro, sonuç veya model config kullanılmaz. Timestamp'siz eski kaynakların geçmiş revizyonlarını yeniden kurmak mümkün değildir; dondurulmuş sinyal kaydı esastır ve sonradan yeniden hesaplanmaz.

`cloud_baslat.py`, ana motor/worker görevi, volume, push, VAPID, HTTPS ve health değişmedi. JSON atomik kayıt/lock ve özel veri yolları korunur. Mevcut tarama/batch sonuçları kullanılır; yeni ağ çağrısı yoktur.

Testler: `tests/test_nihai_karar.py`, `tests/test_nihai_karar_ui.cjs`, mevcut tam Python ve JS/browser smoke grupları. Gerçek piyasa/push servisi kullanılmaz; HTTP testleri geçici veri köküyle çalışır. iPhone boyutlu Chromium smoke, gerçek iPhone/WebKit doğrulaması değildir.
