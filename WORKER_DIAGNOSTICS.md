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
