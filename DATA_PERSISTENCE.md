# Ortak kalıcı veri katmanı

Yol yönetimi `veri_yollari.py` içindedir. Environment değişkenleri process başlatılmadan önce tanımlanmalıdır; çalışan process içinde veri kökü değişimi desteklenmez.

## Envanter ve veri ayrımı

| Veri | Environment yokken mevcut yer | BIST_DATA_DIR tanımlıyken | Web erişimi |
|---|---|---|---|
| bist_data, gun_ici_top10, gun_ici_tum JSON | webapp/data/ | public/ | /data/dosya.json |
| yarin_top10 ve yarin_top10_canli JSON | webapp/data/ | public/ | /data/dosya.json |
| ai_ogrenme_ozeti, ai_ogrenilmis_agirliklar JSON | webapp/data/ | public/ | /data/dosya.json |
| kap_alarmlar (kullanıcı fiyat alarmı değildir) | webapp/data/ | public/ | /data/kap_alarmlar.json |
| makro_canli_etki, makro_kaynak_durum JSON | webapp/data/ | public/ | /data/dosya.json |
| Şirket haber özetleri: sirket_haberleri.json | webapp/data/ | public/ | /data/sirket_haberleri.json |
| sektor_haritasi, sirket_site_haritasi JSON | webapp/data/ | public/ | /data/dosya.json |
| Günlük immutable tahmin arşivi | webapp/data/yarin_top10_arsiv/ | archives/yarin_top10_arsiv/ | /data/yarin_top10_arsiv/YYYY-MM-DD.json |
| Manuel seviyeler | .local/user-data/kullanici_seviyeleri.json | private/user-data/ | Yalnızca kullanıcı API’si |
| AI/MANUEL fiyat alarmları | .local/user-data/fiyat_alarmlari.json | private/user-data/ | Yalnızca kullanıcı API’si |
| pending_notifications ve delivery kayıtları | fiyat_alarmlari.json içinde kullanıcı anahtarlı | Aynı private alarm dosyası içinde | Static erişim yok |
| Push subscriptions | .local/user-data/push_subscriptions.json | private/user-data/ | Static erişim yok |
| Ana motor health, öncelik kuyruğu, şirket sitesi state | .local/runtime/ | runtime/ | Yalnızca güvenli /health özeti |
| KAP görülen ID’ler | kap_son_gorulen.json (repo kökü) | runtime/kap_son_gorulen.json | Static erişim yok |
| makro_gorulen, canli_motor_durum JSON | webapp/data/ | runtime/ | Static erişim yok |
| tahmin_gecmisi, gun_ici_gecersiz_semboller JSON | webapp/data/ | runtime/ | Static erişim yok |
| ai_ogrenme_gecmisi, haber_zeka_gecmisi, makro_ai_gecmisi JSON | webapp/data/ | runtime/ | Static erişim yok |

Kullanıcı verileri, subscription keys ve pending olayları hiçbir public dizine taşınmaz. Runtime’ın bazı eski dosyalarının lokal fiziksel konumu geriye uyumluluk için korunur; web sunucusu bu iç dosyaları sunmaz. Legacy JSON backup/örnek dosyaları iş motorlarının aktif veri kaynağı değildir. Eski patch/kurulum ve backup kaynak scriptleri aktif worker’a bağlanmadığı için yeniden yazılmadı.

Web/worker aynı root’taki public çıktıları, archive, kullanıcı alarm/outbox/subscription kayıtlarını ve runtime state’i paylaşır. Uygulama kodu, index.html, service worker, manifest ve ikonlar repo/webapp içinde kalır; volume’dan uygulama kodu sunulmaz. Static `/data/...` adresleri korunur ve doğru volume dizinine yönlendirilir. Directory listing, path traversal, iç kayıt dosyaları ve dizin dışına çıkan symlink’ler engellenir. Root/private/runtime çakışmaları başlangıçta reddedilir.

## Tek volume örneği (deployment yapılmaz)

Aynı kalıcı POSIX disk iki process’e aynı mount yoluyla görünmelidir:

```
BIST_DATA_DIR=/mnt/bist-data
```

Bu değer mutlak bir mount yolu olmalı ve hem web hem worker environment’ında aynı olmalıdır:

```
/mnt/bist-data/
  public/
  private/user-data/
  runtime/
  archives/yarin_top10_arsiv/
```

Repo kökünde ayrı process komutları:

```
python web_server.py
python ana_motor.py
```

`BIST_DATA_DIR` yoksa eski lokal klasörler kullanılır. Eski `BIST_USER_DATA_DIR` ve `BIST_RUNTIME_DIR` override’ları lokal kullanım için korunur. Ortak root kullanırken bunları kaldırın veya sırasıyla `/mnt/bist-data/private/user-data` ve `/mnt/bist-data/runtime` olarak eşitleyin; çelişen değerler sessizce başka diske yazmak yerine hata verir. `BIST_DATA_DIR` web root altında olamaz. Volume izinleri iki process’in erişimine uygun olmalıdır; oluşturulan dizinler 0700, migration/private JSON dosyaları 0600’dür. En kolay seçenek aynı OS kullanıcı kimliğiyle çalıştırmaktır.

Bir sağlayıcı iki ayrı servise aynı POSIX volume’u mount edemiyorsa yalnızca aynı BIST_DATA_DIR metnini ayarlamak veri paylaşımı sağlamaz. Bu sürüm nesne depolama veya dağıtık veri tabanı değildir. flock, atomic rename/hard link ve fsync semantiğini sağlayan disk gerekir; tek aktif ana worker kullanılmalıdır.

## Geriye uyumlu migration

Otomatik migration veya eski private dizine sessiz okuma fallback’i yapılmaz: bunlar volume ile repo arasında iki ayrı canlı veri kaynağı yaratabilir. Environment yokken doğrudan eski yollar kullanılır. Cloud root’a geçişte iki process’i durdurup tek seferlik kopyalama yapın:

```
BIST_DATA_DIR=/mnt/bist-data python veri_yollari.py --migrate
```

Kaynak mevcut checkout’taki `webapp/data`, `.local/user-data`, `.local/runtime` ve kök KAP kayıt dosyasıdır. JSON’lar kategoriye göre yeni root’a kopyalanır; kaynaklar silinmez. Byte içerikleri korunur. Dosyalar atomik create ile eklenir, hedefte bulunan dosyalar ve snapshot’lar ASLA overwrite edilmez. Migration tekrar çalıştırılabilir; `.migration.lock` eşzamanlı migration’ları sıraya alır. `.lock`/temp dosyaları kopyalanmaz. Kaynaklar eski özel override dizinlerindeyse önce bunların JSON’larını doğru hedef kategorisine kontrollü olarak aktarın; varsayılan migration bunları otomatik keşfetmez.

Migration mevcut hedefle veri birleştirme yapmaz. Başlamadan önce kaynak/hedef yedeği alın ve iki process’in kapalı olduğundan emin olun. Bu geliştirme adımında gerçek kullanıcı dosyaları taşınmadı; migration yalnızca geçici test dizinlerinde uygulandı.

Yolları veri içeriğini okumadan görmek için:

```
BIST_DATA_DIR=/mnt/bist-data python veri_yollari.py
```

## Doğrulama ve deployment öncesinde

Testler temp volume kullanır; web API’sinde oluşturulan alarm ayrı worker subprocess’iyle okunup tetiklenir, web aynı sonucu görür. Snapshot adresleri, private/runtime erişim engeli, env’siz eski yollar, aktif modüllerin ortak köke bağlanması, symlink ve çelişen konfigurasyon, tekrar edilebilir migration kontrol edilir. Atomic kullanıcı kayıt ve immutable snapshot testleri de korunur.

Gerçek deployment bu adımda yapılmadı. Sağlayıcının ortak volume desteği, POSIX kilit/atomic yazım semantiği, kalıcı disk izinleri, backup/restore, kontrollü migration ve process supervision doğrulanmalıdır. HTTPS/VAPID ve gerçek cihaz push kontrolleri için PUSH_SETUP.md; worker periyotları ve çalıştırma için ANA_MOTOR_SETUP.md kullanılmalıdır.

Canonical haber state’i `runtime/haber_dedup.json`, güvenli kart çıktısı `public/canonical_haberler.json` altında tutulur. Kaynaklar arası tekilleştirme ve eski haber ekranı uyumluluğu HABER_DEDUP.md’de açıklanmıştır.

## Ortak AI kayıtları

`ai_agirliklari.json`, `ai_fiyat_teyit.json` ve kilitleri runtime altında private kalır. `ai_hisse_ozetleri.json` güvenli ortak public projeksiyondur. Yeni sinyaller mevcut `ai_ogrenme_gecmisi.json` içine ORTAK_AI modeliyle eklenir; BIST_DATA_DIR ile bu geçmiş runtime’a gider, yerelde eski yol korunur ve HTTP erişimi engellenir. Ayrıntılar AI_KARAR_CORE.md’de.

## Performans kayıtları

performans_durum.json, performans_fiyat_cache.json ve yarin_top10_sonuclar.json runtime/private; performans_gunluk.json, performans_ozeti.json ve onerilen_agirliklar.json public projeksiyonlardır. Sonuçlar mevcut öğrenme geçmişinin aynı sinyal/vade kaydını genişletir. Arşive yazılmaz; web ve worker aynı BIST_DATA_DIR ile aynı sonuçları görür. Ayrıntılar PERFORMANS_SETUP.md'de.

Yarın kalibrasyon modeli ve sürüm geçmişi `runtime/yarin_kalibrasyon.json` ve `runtime/yarin_agirlik_gecmisi.json` altında private kalır. `public/kalibrasyon_durumu.json` güvenli rapordur. Yeni immutable arşivlerde ham/shadow karşılaştırma listeleri tahmin anında dondurulur; eski arşivler değiştirilmez. Environment yoksa runtime `.local/runtime`, public `webapp/data` olarak korunur. Ayrıntılar YARIN_KALIBRASYON.md'de.

Gün İçi bağımsız kayıtları `runtime/gun_ici_sonuclar.json`, `runtime/gun_ici_mumlar.json`, `runtime/gun_ici_agirliklari.json`; public raporları `gun_ici_performans.json` ve `gun_ici_onerilen_agirliklar.json`'dır. Yarın model/arşiv dosyalarını kullanmaz. Ayrıntılar GUN_ICI_PERFORMANS.md'de.

`public/piyasa_durumu.json` ortak güvenli rejim/breadth/sektör RS raporudur. Gün İçi, Yarın ve ortak AI kayıtları kullanılan küçük bağlamı ayrı ayrı dondurur; canlı rapor geçmişe yazılmaz. Mevcut sektör haritası salt okunur. PIYASA_BAGLAMI.md'de puan zinciri, tazelik ve kapanış kısıtları açıklanmıştır.

Railway için aynı `/data` metnini iki servise yazmak ortak disk sağlamaz. Railway volume tek servise bağlanır. Mevcut JSON/flock mimarisiyle hazırlanmış çözüm tek serviste ayrı web/worker process'leridir; RAILWAY_DEPLOY.md'ye bakın. İki ayrı Railway servisi hedefi için ortak transactional veri deposu ayrıca gereklidir.
