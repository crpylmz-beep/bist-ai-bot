# BIST geliştirme incelemesi — 10.10.2026

İncelenen depo: `crpylmz-beep/bist-ai-bot`. Başlangıç commit'i:
`6481d9c` (main üzerindeki mevcut kod). Dal: `feature/bist-development`.
Ayrı worktree: `/workspace/bist-development`; ana kopya: `/workspace/bist-ai-bot`.
Depo yeniden tasarlanmadı. İnceleme kod ve yerel testlere dayanır; canlı sistemin
çalışması veya tahmin doğruluğu hakkında production doğrulaması yapılmadı.

## Mimari ve uygulama durumu

| Özellik | Kod kanıtı | Durum ve sınır |
| --- | --- | --- |
| Uygulama mimarisi | `bist_bot.py`, `canli_motor.py`, `ana_motor.py`, `ana_motor_gorevleri.py`, `web_server.py` | Python modülleri; borsapy/pandas teknik analiz, Telegram arayüzü, zamanlanan worker, HTTP API ve statik web arayüzü mevcut. Yedek ve patch dosyaları aktif özellik kanıtı olarak sayılmadı. |
| TOP 10 | `bist_bot.py:yarin_top10_listesi`, `gun_ici_top10_tara`, `tepki_top10` | Yarın, gün içi ve tepki modelleri ayrı. Yarın seçiminde ham puan ≥55 kapısı, kalibrasyon, piyasa etkisi, sınırlı öğrenme katkısı ve ilk 10 seçimi mevcut. |
| 60 aday taraması | `bist_bot.py:bist_tara`, `gun_ici_top10_tara`; `WorkerTasks.full_scan`; `gunluk_al_sat.py:one_round` | Tüm evren taraması ve parça parça analiz mevcut. Günlük AL/SAT detay limiti 30, dönen evren partisi 10. Özel, garanti edilmiş 60 adaylık iki aşamalı seçim sözleşmesi bu yollarda uygulanmış değil. Koddaki 60 günlük vade veya süreler aday sayısı değildir. |
| Yarın için TOP 10 | `yarin_top10_kilitli_kaydet`, `yarin_snapshot_modeli`, `WorkerTasks.tomorrow` | Günlük değişmez snapshot/arşiv, baz/shadow/öğrenilmiş listeler, pozitif kapanış havuzu mevcut. Pozitif havuzdan TOP10/30/50 ölçümü var. |
| Hisse için yarın planı | `yarin_plani.py:build`, `get_plan` | Kapalı günlük mumlardan giriş, hedef, stop ve risk/getiri hesabı mevcut; TOP 10 sıralamasından bağımsız. |
| Günlük AL/SAT | `gunluk_al_sat.py:evaluate`, `GunlukAlSat.one_round`; worker callback'i | Gerçek kapalı 5dk mumları, teyit aileleri, likidite, eskilik, uzamış hareket cezası ve sinyal yaşam döngüsü mevcut. Bu motor gün içi aday üretir; otomatik emir sistemi değildir. Etkinliği flag ve veri kaynağına bağlı. |
| RSI/MACD/SMA/EMA | `bist_bot.py:hisse_analiz_hesapla`, `teknik_gostergeler.py:rsi/macd/ema`, `yarin_plani.py`, `gunluk_al_sat.py` | Hesaplar uygulanmış. EMA günlük plan ve gün içi motorlarda kullanılıyor. |
| VWAP/OBV/Bollinger/hacim/momentum | `teknik_gostergeler.py:calculate`, `features`, `shadow` | Kapalı mum, veri yeterliliği ve eskilik kapılarıyla uygulanmış. Günlük 20 bar VWAP referansı ile seans VWAP'ı ayrılıyor; bazı katkılar shadow, hepsi aktif TOP 10 ağırlığı sayılmaz. |
| Piyasa rejimi/sektör | `piyasa_baglami.py:build_measurement`, `build_sectors`, `effects`, `usable_context` | XU100 bağlamı, piyasa genişliği, sektör üyeleri ve göreli güç mevcut. Doğrulanmış resmi endeks veya sentetik üye referansı kullanılıyor; eksik veri kontrolü var. |
| Öğrenen sistem | `yarin_kalibrasyon.py:YarinKalibrasyon`, `top10_learning_context`, `top10_learning_adjustment`; `performans_motoru.py:controlled_context/controlled_score` | Geçmiş tamamlanmış sonuçlardan kontrollü istatistiksel katkı, örnek eşiği, baz karşılaştırması, shadow ve geri alma yolları mevcut. TOP 10 indikatör katkısı toplam ±3 ile sınırlı; 1/3/5 gün ağırlıkları %80/%15/%5. Genel amaçlı eğitilmiş LLM olduğu sonucu çıkarılamaz. |
| 1/3/5/10/20/60 gün takibi | `ai_karar_motoru.py:HORIZONS`; `performans_motoru.py:outcome/reports`; `sinyal_performansi.py:quality/aggregate` | İşlem seansı takibi, tamamlanmış sonuç, getiri ve MFE/MAE ölçümleri mevcut. Vade mevcut olması yeterli olgunlaşmış canlı örnek bulunduğunu kanıtlamaz. |
| Tahmin başarısı | `top10_ogrenme_performansi.py:comparison/aggregate`; `/api/top10-learning-performance` | Değişmez aynı snapshot üzerinden baz/öğrenilmiş TOP 10 karşılaştırması ve veri kalite kapıları mevcut. Başarı yüzdesi bu oturumda canlı veriden hesaplanmadı. |
| Alarm/bildirim | `fiyat_alarm_motoru.py`, `push_bildirim_motoru.py`, `kullanici_kayitlari.py`, `webapp/service-worker.js`; worker alarm/push işleri | Manuel ve AI seviyeleri, tek seferlik kontrol, outbox ve opt-in Web Push uygulanmış. Production VAPID, HTTPS ve zamanlayıcı işleyişi doğrulanmadı. |
| Merkezi AI asistanı | `ai_karar_motoru.py`; `webapp/index.html:goAI` | Ortak açıklanabilir karar/AI özetleri mevcut. Merkezi konuşma ekranı tamamlanmamış: `goAI` henüz sonraki aşama uyarısı gösteriyor. Haber/makro puanlarının varlığı sohbet asistanı anlamına gelmez. |
| Web/mobil | `web_server.py:BistHandler`, `webapp/index.html`, manifest ve service-worker; `tests/test_iphone_layout.cjs` | Web/API, responsive ekranlar, kurulabilir PWA ve push mevcut. Ayrı native mobil uygulama doğrulanmadı. Service-worker canlı veri/HTML offline cache yapmıyor. |
| Çok dilli altyapı | Aktif `webapp/index.html` (`lang=tr`) ve HTTP API incelemesi | Dil kataloğu, locale seçimi ve çeviri servis akışı doğrulanamadı; arayüz Türkçe metinler kullanıyor. HTTP sunucusunun `translate_path` metodu dosya yolu çözer, dil çevirisi yapmaz. |
| Testler | `tests/test_*.py`, `tests/*.cjs` | unittest, Node VM smoke ve Playwright mobil/masaüstü testleri mevcut. Bu çalışmanın sonuçları ayrı test raporunda. |

## İlk güvenli değişiklik

Eksik: `top10_learning_context` raporu yüklerken yedi günlük yaşı doğruluyordu;
`top10_learning_adjustment` yalnız gelecekteki/eksik zamanı kontrol ediyordu.
Önceden yüklenmiş READY bağlamının sonradan tekrar kullanılması, eski kanıtın
katkı üretmesine ve baz sırayı değiştirmesine izin veriyordu.

Yeni testlerde eski bağlam baz `[80, 79.5]` sırasını `[80.25, 80]` olarak
değiştirdi; eskilik kontrolü ve sıralamanın korunması testleri başarısız oldu.
Düzeltme, hesap anında aynı yedi günlük sınırı kontrol eder ve aşıldığında
`STALE_REPORT`, sıfır katkı ve boş gerekçeler döndürür. Tam yedi günlük rapor
kullanılabilir. Tek cache okuması, baz puan/sıra, mevcut aday uygunluk kapıları
ve snapshot sözleşmesi korunur. Yeni performans iddiası veya ağırlık değişikliği yok.

## Bağımlılıklar ve geliştirme sırası

Depo Python 3.13 öneriyor; ortam Python 3.12.14. Sabitlenmiş requirements ayrı
`/workspace/bist-venv` ortamına kuruldu. Başlangıçtaki beş TOP 10 test hatası
eksik `borsapy` bağımlılığından kaynaklandı. Kaliteli kapalı OHLCV, XIST takvimi,
doğrulanmış sektör eşlemesi, snapshot zamanları ve tamamlanmış tahmin sonuçları
analiz/öğrenme için temel bağımlılıklar. Push production anahtarları bu oturumun
kapsamı dışında.

1. TOP 10: aday tekrarı, eşit puan deterministik sıralama, eksik/eski veri ve
   uygunluk kapılarını testlerle incele. 60 aday için evren kapsamı, likidite ve
   seçim kalitesini tanımlayan saf fonksiyon + test sözleşmesi oluştur.
2. Performans: mevcut eşleştirilmiş raporda tamamlanan gün/örnek kapsamını,
   1/3/5/10/20/60 gün olgunlaşmasını ve eksik veri nedenlerini ölç; doğruluk
   artışını yalnız ileriye dönük baz karşılaştırmasıyla raporla.
3. Öğrenme: aile/kombinasyon korelasyonu, rejim/sektör örnek yeterliliği ve
   shadow karşılaştırmasını genişlet; yeterli örnek olmadan aktif ağırlık artırma.
4. Günlük AL/SAT: dönen evren kapsamı, veri eskiliği, aday seçimi ve sinyal
   performansını doğrula. Mevcut gün içi ve yarın modellerini ayrı tut.
5. Merkezi AI ekranı, PWA geliştirmeleri ve metin kataloglarına dayalı çok dil.

## Korunan sınırlar

PostgreSQL migration, `v6_storage`, Railway ayarları ve `STORAGE_BACKEND`
değiştirilmedi. Veri klasörlerinde kod/veri değişikliği yapılmadı; test çıktıları
ve geçici çalışma verileri `/workspace/scratch` ve geçici dizinlere yönlendirildi.
Migration, production deployment, canlı veri yazımı, main merge veya remote push
yapılmadı. PostgreSQL/storage/disk yönetimi testleri bu geliştirme regresyon
kapsamına alınmadı; yalnız ilgili uygulama testleri çalıştırıldı.
