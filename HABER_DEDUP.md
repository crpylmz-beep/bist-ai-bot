# KAP + şirket sitesi canonical haber tekilleştirme

`haber_tekillestirme.py` her iki haber kaynağının AI/history/alarm/öncelik tetiklerinden önce kullanılır. Crawling, makro, teknik puanlama, TOP10/snapshot, kullanıcı fiyat alarmları ve fiyat push outbox modeli değişmez. İlk site senkronu eskisi gibi sessizdir.

## Model ve eşleştirme

Private state: merkezi runtime altında `haber_dedup.json` (BIST_DATA_DIR varsa root/runtime/). Model: canonical_id, sembol, ana_baslik, ana_kaynak, kaynaklar[], ilk_gorulme, son_gorulme, kap_url, sirket_url, hashler, duplicate_status, kaynak variants, bir kez hesaplanan analiz/alarm, tamamlanan yan etki aşamaları. Public `canonical_haberler.json` yalnızca güvenli kart alanlarını içerir; eşleştirme metinleri ve effect ledger public olmaz.

Kaynak önceliği KAP’tır. Şirket sitesi önce gelirse o kayıt hemen işlenir. KAP sonradan geldiğinde başlık/ana kaynak ve alternatif URL metadata’sı güncellenir; canonical_id ve ilk analiz korunur. Kaynak etiketi KAP, ŞİRKET_SITE veya KAP + ŞİRKET_SITE olur. İlk kaynağın analizini KAP gelince yeniden hesaplamak ikinci AI etkisi yaratacağından yapılmaz. Kaynak zenginleştirme aynı history satırını günceller.

Zaman penceresi **6 saat**: `NEWS_DEDUP_WINDOW_SECONDS=21600`; 60 saniye–7 gün arası ayarlanabilir. Kaynak kesin publication time varsa o kullanılır; yalnızca gün verilen veya zamanı eksik kayıtlarda İstanbul offset’li keşif zamanı kullanılır. Pencere ilk kaynak zamanına bağlıdır, sürekli eklenen varyantlarla ileri taşınmaz.

Önce farklı sembol, uzak zaman, çelişen sayısal tutarlar/para birimleri, iptal/fesih/uzatma gibi farklı olay aşamaları ve farklı ayırt edici başlık parçaları ayrılır. Normalize Türkçe karakterler, şirket/ticker/yeni/tutarında/imza dolgu parçaları temizlenir. Tutarlar milyon/milyar ve TL/USD/EUR üzerinden normalize edilir.

- **EXACT_DUPLICATE:** aynı normalize başlık ve yeterli bilgi (kısa başlıkta aynı kaynağın aynı URL/metin kaydı tekrar okunması da idempotenttir); metin varsa çelişmemesi gerekir (en az .65 benzerlik). Ayrıca uzun metin hash eşleşmesi + en az iki ortak başlık token’ı; ya da aynı URL + en az .80 başlık/örtüşme ve üç ortak token.
- **LIKELY_DUPLICATE:** eşit açık tutar + en az .75 token örtüşmesi + üç ortak token; veya en az .88 başlık SequenceMatcher, .80 örtüşme, iki anlamlı ortak parça ve varsa .75 metin benzerliği.
- **DIFFERENT_EVENT:** bunları sağlamayan veya ayırt edici bilgiyle çelişen kayıt. “Sözleşme” gibi tek genel kelime yeterli değildir.

Bu konservatif deterministic/fuzzy ilk sürümüdür; ağır LLM veya anlam garantisi değildir. Çok kısa/eksik kaynak başlıklarında yanlış birleştirmek yerine ayrı kayıt tercih edilir. Kaynak ayrıntıları ileride inceleme/eşik ayarı için tutulur. Aynı generic başlığın farklı sözleşmelerde kullanılması ve az metadata hâlâ sınırlamadır.

## Eşzamanlılık ve yan etkiler

Canonical dosya flock altında okunur, güncellenir ve atomik yazılır; eşzamanlı KAP/site veya iki process tek kayıt oluşturur. AI sonucu ve alarm kararı bir kez kaydedilir. Haber history’sinde canonical_id aynı id olarak kullanılır; ikinci puan satırı eklenmez. Eski history satırları korunur. KAP haber alarm kartının ID’si de canonical_id’dir.

Öncelikli kuyruğun var olan JSON’unda `_news_event_ids` alanı desteklenir. Canonical ID ile enqueue, idempotency kaydı ve sembol işi aynı atomik queue yazımında saklanır; tekrar/restart ikinci işi oluşturmaz. Önceki stock/version biçimi geriye uyumlu okunur. Tekilleştirme dışında teknik hesap değişmez.

Bildirim callback’i verilirse canonical kimliğiyle bir kez çağrılır; testlerde fake push-event writer kullanılır. **Mevcut sistemde şirket/KAP haberleri için gerçek Web Push outbox hattı yoktur; bu adım yeni haber push özelliği eklemez.** Fiyat alarm pending_notifications ve push motoru değiştirilmez. Yapılandırılmamış notification aşaması SKIPPED olarak tutulur; SENT iddiası yapılmaz.

Yan etki başarısızlığı tekrar denenir; tamamlanan AI/alarm aşamaları yinelenmez. Kalıcı queue/history ve alarm projection canonical ID ile idempotenttir. Genel harici notification callback’i de canonical ID’yi idempotency key olarak kullanmalıdır: harici gönderim başarıyla gerçekleşip ledger checkpoint’inden önce process kesilirse iki sistemi kapsayan dağıtık exactly-once garantisi yoktur. Gerçek gönderici entegrasyonunda mevcut push delivery claim/idempotency yaklaşımı kullanılmalıdır.

## Web ve doğrulama

Mevcut KAP/Haber ekranı canonical JSON’u ve legacy kap_alarmlar JSON’unu birlikte okur. canonical_id ile tek kart bırakılır; eski aynı başlık/sembol/yakın tarih kartı bastırılır. Canonical dosya yoksa eski ekran çalışır. Kartta kaynak etiketi görünür, başlık/metin alanları escape edilir. Şirket haber özetleri de canonical_id taşıyarak aynı dosyada tekrar kart üretmez.

Testler gerçek KAP/site/push servislerini çağırmaz. Exact/fuzzy, farklı tutar/karşı taraf/iptal, iki kaynak sırası, sembol/tarih penceresi, threaded ve process concurrency, tek AI/alarm/fake push event/queue, retry, kalıcı queue idempotency, eski history ve frontend tek kart/escaping doğrulanır. Deployment ve eksik 260 site keşfi yapılmadı.
