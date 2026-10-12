# Web/PWA push altyapısı

Bu adım zamanlayıcı veya deployment eklemez. Sunucu `web_server.py`, tek tur gönderim `push_bildirim_motoru.bildirimleri_gonder()` veya `python push_bildirim_motoru.py` üzerinden çalışır. Fiyat alarm motorunun mevcut kullanıcıya özel outbox olaylarını tüketir. Gerçek gönderim için requirements.txt içindeki pywebpush gerekir.

## Yapılandırma

Sunucu ve tek tur gönderici aynı environment ve kalıcı özel dizini kullanmalıdır:

- `VAPID_PUBLIC_KEY`: URL-safe base64, uncompressed P-256 public key.
- `VAPID_PRIVATE_KEY`: pywebpush/py-vapid uyumlu private key veya güvenli PEM dosyasının yolu.
- `VAPID_SUBJECT`: `mailto:...` ya da HTTPS iletişim adresi.
- `BIST_USER_DATA_DIR`: isteğe bağlı, varsayılan `.local/user-data/`.

VAPID anahtarlarını güvenli ortamda py-vapid ile üretin; private key ve environment dosyalarını repoya koymayın. Public key `/api/push/config` üzerinden paylaşılır; private key hiçbir API yanıtında bulunmaz. Subscription değişiklikleri mevcut HttpOnly kullanıcı cookie’si ve aynı-origin JSON API üzerinden yapılır. Kullanıcı kimliği şimdilik tarayıcı oturumuna bağlıdır; cookie silinmesi veya başka cihaz mevcut alarmlara erişimi taşımaz.

Subscription’lar `.local/user-data/push_subscriptions.json` içinde kullanıcı anahtarlı saklanır. Her endpoint tek kullanıcıya aittir. FCM, Mozilla, Apple ve Windows push HTTPS endpoint’leri desteklenir; özel ağ adresleri reddedilir. İzin yalnızca “Bildirimleri Aç” düğmesiyle istenir. Kapatma backend kaydını pasifleştirir ve tarayıcı subscription’ını kaldırır.

## Teslim ve hata davranışı

Mevcut `fiyat_alarmlari.json` içindeki `pending_notifications` olaylarına subscription bazlı `deliveries` eklenir. Gönderim öncesi atomik `SENDING` kaydı yazılır. Başarılı gönderim `SENT` ve İstanbul saatinde `sent_at` alır. Tüm aktif alıcılar başarıyla tamamlanınca olay `SENT` olur. Başarılı alıcı tekrar gönderilmez. İzinli kullanıcı aboneliği yoksa olay kuyrukta kalır. 404/410 endpoint’i pasifleştirir. Kesin başarısızlıklar `FAILED`, hata sınıfı ve `retry_count` ile saklanır; sonraki tek turda tekrar denenir. Hata metinleri secret/endpoint içerebileceğinden kaydedilmez.

Kesinti veya ağ zaman aşımı sonrası teslim sonucu belirsiz olabilir: `SENDING` otomatik tekrar denenmez. Operatör sağlayıcı sonucunu incelemelidir; teslim edilmediği doğrulanırsa ilgili delivery `FAILED` yapılabilir. HTTP push kabulü cihazda bildirimin görüldüğünü garanti etmez. Service worker bildirimi event ID tag’iyle gösterir. Subscription kilidi gönderim turu boyunca tutulur; eşzamanlı göndericiler seri çalışır, kapatma devam eden gönderimin tamamlanmasını bekleyebilir.

## PWA ve iPhone

Yeni manifest, raster uygulama ikonları ve `/service-worker.js` eklenmiştir. Service worker piyasa verilerini önbelleklemez. Bildirime tıklama aynı-origin `/?stock=SEMBOL` adresini açar; veri yüklenince ilgili hisse detayı gösterilir.

Gerçek kullanım için geçerli sertifikalı HTTPS gerekir. Mevcut geliştirme sunucusu HTTP’dir; bu adım TLS/deployment yapmaz. iPhone/iPad için iOS/iPadOS 16.4+ ve Safari’den Ana Ekran’a eklenmiş PWA gerekir. PWA’yı Ana Ekran’dan açıp izin düğmesine basın. Odak modu, OS ayarları ve bağlantı durumu teslimi etkileyebilir. VAPID anahtarlarını sabit tutun; anahtar rotasyonu tarayıcıda kapatıp yeniden açmayı gerektirebilir.

Testler gerçek push servisini çağırmaz: `python -m unittest discover -s tests -v` ve `node tests/test_push_frontend.cjs`.

Ortak volume yapılandırıldığında subscription ve outbox yolu `BIST_DATA_DIR/private/user-data/` olur. Web ve gönderici aynı fiziksel mount’u görmelidir. Environment tanımlanmamışsa yukarıdaki lokal yollar korunur. Ayrıntılar DATA_PERSISTENCE.md’dedir.
