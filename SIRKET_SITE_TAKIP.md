# Resmi şirket duyuru takibi

Mevcut `SirketSiteMotoru.tek_tur()` sözleşmesi ve ana motor bağlantısı korunmuştur. Eksik şirket URL’leri bu adımda aranmaz; sadece mevcut haritanın site bulunan kayıtları kullanılır. Haritadaki ilk resmi URL başlangıç noktasıdır. KAP semantik dedup veya deployment eklenmedi.

## Keşif ve çalışma bütçesi

Beş kaynak aşaması: resmi başlangıç URL → yatırımcı ilişkileri/ilgili bölüm → RSS/Atom → sitemap.xml ve en fazla iki ilgili alt sitemap → duyuru/haber listesi. Sayfa bağlantılarından yatırımcı ilişkileri, duyuru, haber, basın, finansal sonuçlar, faaliyet raporları, sunum, sözleşme, ihale ve yatırım alanları keşfedilir. İlk keşif aşamalıdır; her şirket tek turda bitmek zorunda değildir. Bulunan RSS/Atom tercih edilir. Sadece ilgili sitemap URL’leri izlenir, site tamamı crawl edilmez.

- `COMPANY_SITE_BATCH_SIZE`: varsayılan **15 şirket**, sınır 1–20.
- Her şirket/tur en fazla **4 HTTP isteği** (robots ve redirect dahil).
- Kaydedilmiş cursor ile bir sonraki batch kaldığı yerden devam eder; backoff’taki şirketler kuyruğu tıkamaz.
- `COMPANY_SITE_DOMAIN_DELAY_SECONDS`: varsayılan **2 saniye**; robots crawl-delay de dikkate alınır. Uzun bekleme sonraki tura ertelenir.
- Connect/read timeout: 5/15 saniye. Yanıt limiti 512 KB; redirect sayısı ve okuma süresi sınırlandırılır.
- Site hatası diğer şirketleri durdurmaz. Ana motor kapanırken yeni şirket/HTTP işi başlatılmaz; başlamış timeout’lu istek tamamlanır. Başlangıç backoff 300 sn, üstel artış en fazla 24 saat; 403 en az 1 saat, 429 en az 15 dakika ve Retry-After dikkate alınır. Domain genelinde de erişim beklemesi tutulur.
- TLS doğrulaması açık; private IP’ler ve resmi domain dışına redirect reddedilir. HTTP/HTTPS, www, fragment ve yaygın tracking parametreleri kimlikte normalize edilir. Domain değişen resmi redirect’ler otomatik güvenilir sayılmaz; doğrulanmış URL/allowlist çalışması gerektirebilir.

Batch şirket sayısıdır, istek sayısı değildir. Site sayısı ve ana motorun 900 saniyelik şirket periyoduna göre bütün haritanın dolaşımı saatler sürebilir. İlk kaynak keşfi birkaç dolaşım gerektirebilir. Production öncesinde erişim ve tazelik hedeflerine göre bu periyot ayarlanmalıdır.

## İlk senkron ve içerik kimliği

Her kaynak URL ilk görüldüğünde yanıt içindeki bütün çıkarılabilir duyurular görülmüş olarak saklanır; analiz, hisse tetiklemesi veya alarm üretilmez. Yeni keşfedilen bir alt kaynağın eski arşivi de sessizce baz alınır. Önceki minimum motorun homepage hash’i yeni duyuru baseline’ı kabul edilmez; ilk gerçek kaynak keşfi sessizdir.

Sonraki kontrollerde şirket + canonical duyuru URL’si story key’dir. Tam content ID: sembol, canonical URL, başlık, normalize yayın zamanı ve içerik hash’inden oluşur. Aynı URL’de metin/tasarım güncellemesi ikinci yeni haber üretmez. Kaynağın ilk senkronundan önce yayımlanmış eski tarihli içerik sonradan listede belirse de tetiklenmez. Yayın zamanı yoksa uydurulmaz; `published_at=null`, ayrı `discovered_at` tutulur. Tanınan ISO/RFC tarihler İstanbul saatine dönüştürülür.

RSS/Atom title/link/date/summary/content alanları ve HTML duyuru bağlantıları/article-list kısa metni çıkarılır. Menü/header/footer değişimleri haber değildir. Bu sürüm tüm haber detaylarını veya PDF gövdelerini okumaz; HTML kartı/feed özetini kullanır. Başlık/URL yanında kısa metin bazen yalnızca listede sunulan metin kadar olabilir.

## AI ve teknik kuyruk

Yeni içerik `haber_zeka.kap_haber_analiz_et(..., kaynak='SIRKET_SITESI')` ve `haber_kaydet()` üzerinden mevcut haber puanlama/teknik etki akışına katılır. Teknik formüller tekrar üretilmez. Çıktı etki puanı, yön, güven, önem, gerekçe ve sembol içerir. KAP ve şirket haberleri aynı history dosyasına yazdığından read/modify/write kilitlenir.

Teknik tetikleme var olan `enqueue(sembol, gun_ici_yenile=False)` callback’iyle ana motorun öncelikli kuyruğuna gider. Bağımsız ikinci event bus veya her haber için tam Gün İçi taraması eklenmez. Gün İçi mevcut periyotta yeniden değerlendirilir. Kullanıcı fiyat alarmı ve push outbox’ına şirket haberi doğrudan eklenmez.

İşlenmesi yarım kalan içerik metadata’sı mevcut site state’inde korunur. Aynı content ID/timestamp ile yeniden denenir; tamamlanan AI aşaması tekrar yapılmaz. Başarılı içerik yeniden işlenmez. Teknik kuyruğa yazım ile site checkpoint’i arasındaki süreç kesilmesinde aynı sembol tekrar enqueue edilebilir; mevcut kuyruk sembolü birleştirir. Kaynaklar arası KAP/şirket semantik dedup henüz yapılmaz, ortak content_id/source/url metadata’sı bunun için hazırdır.

## Kalıcı kayıtlar

`BIST_DATA_DIR` kullanılıyorsa:

- `runtime/sirket_site_durum.json`: cursor, kaynak baseline’ları, görülmüş ID/hash’ler, keşif URL’leri, robots cache, domain hız limiti, hata/backoff, yarım iş metadata’sı.
- `runtime/haber_zeka_gecmisi.json`: mevcut haber AI geçmişi; private runtime.
- `public/sirket_haberleri.json`: son 500 güvenli haber özeti ve analiz sonucu. Kullanıcı verisi veya credentials içermez.

Environment yoksa mevcut merkezi lokal yollar kullanılır. Site state ve public özet atomik yazılır; site turu dosya kilidiyle seri çalışır. Public özet JSON hazırdır, bu adımda yeni web kartı eklenmedi.

## İkinci yöntem isteyen kaynaklar ve doğrulama

Tam JavaScript render, CAPTCHA/anti-bot, cookie/auth gerektiren sayfalar, farklı resmi domain’e yönlendirme, PDF-only metin ve açık duyuru/başlık bağlantısı sunmayan sayfalar ayrıca ele alınmalıdır. Script var ve görünür içerik azsa `dinamik_site / ikinci_yontem_gerekli` işaretlenir. Robots yasakları/403/429 bypass edilmez.

Fixture testleri: batch/restart, ilk senkron, duplicate ve eski tarihli içerik, feed/Atom, sitemap index, yatırımcı bağlantıları, timeout izolasyonu, 403/429, robots, domain pacing, hash, yarım işlem retry, shared-root, mevcut AI ve eşzamanlı history yazımı. Gerçek smoke yalnızca iki mevcut resmi URL üzerinde, geçici state ve sahte tetik callback’leriyle yapılır; dış bağlantı hatası unit test başarısını değiştirmez.

Bu geliştirme ortamındaki gerçek smoke: FROTO ve KCHOL resmi URL’leri denendi; ikisinde de DNS `gaierror` nedeniyle içerik okunamadı. Her iki hata izole edildi, state geçici dizinde kaldı ve eski içerik tetiklemesi üretilmedi. Canlı site keşfi henüz dış bağlantıyla doğrulanmış sayılmaz.

Onuncu adım: yeni site içerikleri KAP ile ortak canonical ledger üzerinden analiz ve öncelik kuyruğuna bağlanır. İkinci kaynak AI/alarmı tekrar üretmez; kaynak metadata’sını zenginleştirir. Ayrıntılar HABER_DEDUP.md’dedir.
