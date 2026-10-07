# Worker görev hata teşhisi

Production /health örneği sadece status/failure/retry sayıları içeriyordu. Tek başına bu bilgiler priority/company_site/KAP/performance/full_scan için kesin production hata nedeni değildir. Production logları ve mount içeriği bu geliştirme ortamına ulaşmadı; Railway HTTPS erişimi ortam ağ proxy'sinde 403 ile engellendi. Kaynak koddan doğrulanan sorunlar ve düzeltmeler:

- Priority: analiz/sağlayıcı/persistence exception'ı alt fonksiyonda yutulup None olabiliyor, sonra genel RuntimeError'a dönüşüyordu. Thread/task-local hata capture eklendi; HTTP/network/disk/kod nedeni sabit kodla korunur. Bir hissede exception diğerlerini kesmez; başarısız kuyruk girdileri silinmez.
- Full scan: tüm batch sonuçları None olduğunda cursor ilerlemiyordu. Kalıcı geçersiz batch sonraki hisseleri aç bırakamaz; başarısızlar dayanıklı priority kuyruğuna alınır ve tarama diğer batch'e geçer. Başarısız batch public veriyi boşaltmaz. Kısmi başarı kaydedilir ve kalan kaynak hatası OK diye gizlenmez. Mevcut batch boyutu ve tek technical lane korunur.
- Company site: collector kendi site bazlı backoff'uyla hatalı şirketten sonra devam ediyordu, fakat scheduler'a yalnız haber sayısı dönüyordu. Round'un en ciddi güvenli hata kodu adapter'a aktarılır; per-site request limitleri, robots/SSRF koruması, 403/429 domain backoff'u ve checkpoint aynen korunur. Collector state okuma/yazma gibi dışarıya yükselen hatalar da scheduler'da açık gösterilir.
- KAP: olay işleme exception'ları bir genel RuntimeError'a indirgeniyordu. Disk/kod/HTTP nedeni korunur; yalnız başarıyla işlenen olaylar seen olur, diğerleri sonraki turda tekrar denenir. KAP HTML istemcisi veya dış endpoint değiştirilmedi; site engeli doğrulanmadan erişim bypass'ı eklenmez.
- Performance: provider hata tipi bilinmesine rağmen adapter genel RuntimeError üretiyor, kısmi hatayı ve calibration hatasını OK döndürebiliyordu. Güvenli `error_details` ve TaskIssue eklendi; kayıt edilmiş outcome'lar korunur, sağlayıcı hatası ile calibration/kod/disk hatası ayrılır. Yeterli fiyat gelmeyen vadeler tamamlandı sayılmaz.

## /health ve loglar

Her görev `last_error` nesnesinde `code`, sabit Türkçe `message`, `category`, `retryable` ve varsa yalnız sayısal `http_status` gösterebilir. Ham exception mesajı/URL/token/body/stack locals public health'e girmez. Persisted message/category güvenilmez; public endpoint bunları sabit sözlükten yeniden kurar. Unknown kodlar TASK_ERROR olur. Başarıda güncel hata temizlenir; retry sırasında önceki hata okunabilir.

REMOTE (timeout, connection, HTTP403/429/5xx) ve SOURCE_DATA hataları RETRYING; kısmen tamamlanan bu görevler DEGRADED'dır. Disk doluluğu/izin, configuration ve kod hataları ERROR olarak kalır. ANALYSIS_NO_RESULT gerçek nedeni doğrulanamayan sonuç yok durumudur; ağ hatası olduğu iddia edilmez, ERROR kalır. Retry/backoff tüm hatalarda sürer; failures artar ve mevcut exponential/cap korunur. `retry_in_seconds` kalan süreyi gösterir. Hatalar worker process'i düşürmez; healthy heartbeat task başarısından ayrıdır.

Logs: güvenli code/category ve son dört stack dosya/line/function konumu. Exception args, URL query veya kaynak satırı loglanmaz. Çoklu hatada STORAGE/CODE/CONFIG önceliklidir; geçici bir HTTP hatası gerçek kod veya disk hatasını örtemez.

## Veri güvenliği

Yeni dosya geçmişi/backup yok; capture context sadece çağrı süresince RAM'dedir. State'te görev başına tek son hata bulunur, sınırsız error listesi birikmez. Volume/disk koruması, cache bütçesi, atomic kayıt, 1/2/3/5/10/20/60 günlük outcome, snapshot freeze, ranking ve öğrenme davranışı değiştirilmez; veri silinmez.

## Production doğrulaması

Yeni deploy sonrası her beş görev için /health `last_error.code` ve Logs code/category/stack konumu paylaşılmalı. DISK_FULL ise gerçek kalıcı dosyaları silmek yerine volume büyütülmelidir. REMOTE kodları provider erişim sorunudur; yeni retry ile düzelmesi beklenir. CODE_ERROR veya STORAGE_PERMISSION için stack konumu/ilgili kaynak ve konfigürasyon üzerinden ikinci hedefli düzeltme gerekir. Loglar görülmeden beş production hatasının tümünün giderildiği söylenemez.

## 5 GB volume sonrası sağlayıcı teşhisi

Kullanıcının production health gözleminde STORAGE hataları kalktı; bu ortam production mount veya Railway loglarına erişemiyor. priority/full_scan için TASK_ERROR tek başına TradingView arızasını kanıtlamaz.

Borsapy 0.11.0 `Ticker.history` TradingView providerını kullanır. Provider WebSocket hatasını veya veri gelmemesini `APIError` ile yükseltir; önceki sınıflandırıcı bu özel sınıfı tanımadığından TASK_ERROR üretir. Artık APIError ve status_code, rate limit, authentication, missing data, invalid period/interval ile httpx timeout/network türleri açık sınıflandırılır. APIError'ın bilinen cause'u varsa korunur; mesaj üzerinden tahmin yapılmaz. Nedeni daha daraltılamayan APIError, PROVIDER_API_ERROR olarak retry edilir, OK sayılmaz. Generic RuntimeError UNKNOWN kalır.

`[SOURCE_TRACE]` alt analiz/sağlayıcı fonksiyonunda yakalanan hatanın türünü, aşamasını ve son beş dosya/line/function konumunu kaydeder. Ham mesajlar, kaynak satırları, locals ve URL/token yazılmaz. Böylece TaskIssue üst katmanda yalnız adapter konumunu göstermiş olsa bile asıl hata konumu bulunabilir.

Company site NETWORK_CONNECTION requests bağlantı hatasıdır; geçici olup olmadığı veya hangi domain'in erişilemediği production logları olmadan belirlenemez. DNS ve TLS hataları ayrı kodlanır. Site başına backoff ve checkpoint değişmez. Bu güncelleme bağlantı sağlayıcısını, analiz skorlarını, snapshotları veya disk temizleme mekanizmasını değiştirmez.

## Maskelenmiş kaynak mesajı

Production kullanıcısının paylaştığı priority satır 100 ve full_scan satır 141 trace'leri `TaskIssue` toplama/yükseltme konumlarıdır. Full scan satır 141'e ulaşılması bu batch'te en az bir başarılı sonuç ile en az bir başarısız sonuç olduğunu gösterir; başarısız hissenin alt exception türü veya mesajı bu trace'ten çıkarılamaz. Bu gözlem yeni sağlayıcı sınıflandırmasıyla da kesin kök neden olarak sunulmaz.

`[SOURCE_TRACE]` artık yalnız Railway operasyon loguna 240 karaktere kadar maskelenmiş `message` ekler. Environment secret bağları, URL'ler, credential alanları, bearer/basic değerleri, uzun anahtar benzeri değerler, private dosya yolları, e-posta ve payload/header gövdeleri maskelenir. Mesaj tek satırdır; cause/context zinciri en fazla üç hata ile sınırlıdır. Public health ve runtime task state ham/maskelenmiş exception mesajını almaz, sabit sözlükten mesaj üretmeye devam eder. Kaynak satırları, locals ve ham traceback exception args yazılmaz. Uygulama düzeyi hata ile dış kaynak hatası ayrımı tahmin edilmez; UNKNOWN gerektiğinde kalır.

Company collector site başına yakalanan bağlantı hatasına da SOURCE_TRACE ekler. Scheduler'ın TaskIssue olmayan hataları aynı mekanizmayla loglanır; TaskIssue için önceki alt kaynak kaydı esas alınır. Retry, checkpoint, filtre, skor, tarama boyutu, primary data ve disk cleanup mantığı değişmez. Production'da deploy sonrası SOURCE_TRACE mesajı/türü/konumu görülmeden priority/full_scan arızasının giderildiği söylenemez.

## TradingView invalid symbol / şirket yanıt boyutu

Kullanıcının SOURCE_TRACE logu TradingView `get_history` içindeki `APIError` ve protokolün `invalid symbol` nedenini doğruladı. Borsapy'nin şirket listesi KAP kaynağından gelir, history ise TradingView'den gelir; iki kaynağın sembol kapsamlarının eşit olduğu varsayılamaz. Hatalı sembol adları paylaşılmadığından belirli bir kodun yanlış şirket kodu, delist/eski kod veya TradingView'de desteklenmeyen geçerli BIST kodu olduğu henüz tespit edilemez. Varsayımsal ticker alias veya yatırım filtresi eklenmedi.

`saglayici_sembolleri.bist_symbol` yalnız bilinen `BIST:` prefix ve `.IS`/`.E` suffixlerini normalize eder; Ticker'a kanonik ASCII kod gider, borsapy bir kez BIST exchange ekler. Universe kodları da aynı helper kullanır. `[PROVIDER_SYMBOL]` başarısız kanonik kodu ve tam TradingView eşlemesini operasyon loguna yazar. APIError'ın açık protokol `invalid symbol` cevabı PROVIDER_UNSUPPORTED/SOURCE_DATA olur; genel no-data/network APIError körlemesine bu sınıfa çevrilmez. Kısmen başarılı full scan batch'i kaydedilmeye devam eder ve sorun DEGRADED kalır; tümü başarısız batch cursor ilerletir, hatalar açıkça raporlanır. Priority başarısız kaydı korur, diğerlerini işler. Retry ve kuyruk rotasyonu değişmez; hata OK'e çevrilmez.

Company site yanıt boyut sınırı kod bug'ı değil dış yanıtın önceden tanımlı 512000 byte sınırını aşmasıdır. ValueError bunu yanlışlıkla CODE_ERROR gösteriyordu. ResponseLimitError/SOURCE_RESPONSE_TOO_LARGE sınıflandırması eklendi. Content-Length büyükse body alınmaz; chunked/decompressed stream sınırı aşacak chunk belleğe eklenmeden kesilir ve bağlantı kapanır. 45 saniyelik toplam süre sınırı ayrı NETWORK_TIMEOUT olarak raporlanır. Büyük sayfa kesilip eksik HTML haber gibi işlenmez; site backoff/checkpoint alır, diğer şirketler devam eder. Boyut, SSRF, robots, redirect ve request budget sınırları kaldırılmadı; kalıcı veri/snapshot/puanlama değişmedi.

## Kısmi ilerleme ve görev backoff'u

Kod incelemesinde kısmi başarılı batch'ler dahi her TaskIssue sonrası tüm görevin exponential backoff'unu uzatıyordu. Bu, bir desteklenmeyen sembolün sonraki sağlıklı batch'leri 900 saniyeye kadar yavaşlatmasına yol açabiliyordu. Kaydedilmiş ilerleme (`completed>0`) ve REMOTE/SOURCE_DATA hatası birlikteyse bir sonraki kontrol normal görev aralığında (mevcut minimum 5 saniye) yapılır. DEGRADED, last_error ve artan failures sayacı korunur; hata OK'e çevrilmez. Tam başarısız batch, UNKNOWN/CODE/CONFIG/STORAGE hata veya hiç ilerleme olmaması mevcut exponential backoff'u korur. Sağlayıcı sembol kapsamı, şirket response limitleri, kuyruk rotasyonu, snapshot ve skorlar değişmez.

Bu oturumda çağrılabilir Railway connector/CLI oturumu veya Railway environment binding görünmedi. Public HTTPS kontrolü ortam proxy'sinde 403 ile engellendi; bu production uygulamasının 403 verdiği anlamına gelmez. Proje dazzling-healing, servis bist-ai-bot, production deploy ve gerçek unsupported sembol listesi burada doğrulanamadı. Bu değişiklik code-level ilerleme gecikmesini giderir, production'ın tümüyle stabil olduğu iddia edilmez.

## Pay evreni ve beklenen skip izolasyonu

`borsapy.companies()` KAP `company/generic/excel/IGS/A` listesini sadece ticker/name/city alanlarıyla okur; işlem gören pay veya enstrüman tipi garantisi yoktur. Production örnekleri bu üyelik listesinin TradingView pay kapsamıyla uyuşmadığını doğrular. Her örneğin fon/varant/sertifika/borç ihraççısı türü bu metadata ile kesin atanamaz; isim veya kod uzunluğu blacklist'i eklenmedi. Tarama artık borsapy'nin Borsa İstanbul `hisse_endeks_ds.csv` kaynağından sağladığı `Index('XUTUM').components` pay bileşenlerini kullanır. Bu XUTUM kapsamıdır; endeks dışında kalan bütün BIST ürünlerini veya tüm pazarların paylarını kapsadığı iddia edilmez. Kaynak boş/hatalıysa typed olmayan KAP listesine geri dönülmez, EMPTY_UNIVERSE raporlanır.

Priority'de eldeki doğrulanmış pay evreni dışında kalan kod sağlayıcıya gönderilmeden OUTSIDE_EQUITY_UNIVERSE olarak açık skip edilir. PROVIDER_UNSUPPORTED tekil kodlar kuyruktan kontrollü tamamlanır, full_scan tarafından retry kuyruğuna yeniden eklenmez. `runtime/provider_unsupported.json` en fazla 2000 sembolün son kod/timestamp tanısını atomik tutar; bu yeni bounded diagnostic index'tir, tahmin/performans/kullanıcı geçmişi değildir. Gerçek API/network/analysis hataları kuyrukta kalır ve TaskIssue/backoff korunur. Skip-only batch cursor ilerler, boş public analiz yazılmaz; başarılı veriler normal kaydedilir. Health OK_WITH_SKIPS veya SKIPPED ile processed/successful/skipped/unsupported/failed ve en fazla 25 güvenli sembol/neden gösterir; kritik/outage hataları bu statülere çevrilmez. Skip listesi ve detayları sonraki RUNNING durumunda da korunur.

Şirket round'u başarılı site ziyaretlerini haber sayısından ayrı ölçer. Bir TLS hatası ile diğer başarılı ziyaret varsa DEGRADED ve 30 saniyelik sonraki batch; tüm TLS ziyaretleri başarısızsa CONFIG/ERROR ve mevcut backoff. Site başına BACKOFF, certificate verify=True, robots/SSRF/redirect/response limitleri korunur. Büyük yanıt da kendi sitesinde sınırlı tutulur. processed/skipped sayaçları cooldown ziyaretlerini içerir; son hata kodu private site state'te kalır ve cooldown skip nedeni health diagnostics'te gösterilebilir. Primary /data verileri, yatırım skorları ve snapshot/takip hesapları değiştirilmez.
