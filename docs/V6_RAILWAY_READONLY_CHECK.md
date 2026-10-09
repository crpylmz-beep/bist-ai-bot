# Railway UI ile salt okunur PostgreSQL teşhisi — hazırlanmış, uygulanmamış

## Mevcut sınır

67a7373 kaynak sürümünde `schema --check` yoktur. Eski
`BIST_RUN_POSTGRES_SCHEMA_ONCE=1` başlangıç yolu `schema` çalıştırır ve şema
oluşturabilir. Bu flag teşhis için kullanılmamalıdır. Yeni kod production'a
aktarılmadan yalnız Variables değiştirerek bu kontrol çalıştırılamaz.
Railway log/komut erişimi bu geliştirme ortamında bulunmuyor; gerçek bağlantı,
aktif deployment ve veritabanı durumu doğrulanmış değildir.

## Hazırlanan yöntem

`BIST_RUN_POSTGRES_SCHEMA_CHECK_ONCE=1` yalnız açıkça ayarlandığında başlatıcı,
web ve worker başlatıldıktan sonra ayrı daemon thread'de tek bir subprocess
çalıştırır. Varsayılan kapalıdır. Komut sabittir: `python -B -m v6_storage schema
--check`. Süre sınırı 45 saniyedir; yeniden deneme yoktur. Bir başlatıcı süreci
başına en fazla bir çalıştırma vardır; flag açık bırakılırsa yeniden başlatmada
tekrar kontrol edilir. Dosya tabanlı marker veya `/data` erişimi yoktur.

PostgreSQL kontrolü `SET TRANSACTION READ ONLY` ile migration metadata'sını ve
beklenen migration checksum'larını SELECT ile doğrular. DDL/DML, migration,
ensure(), dosya taşıma/silme ve STORAGE_BACKEND değişikliği yapmaz. Session
ayarları bağlantı içindir; veritabanı log/istatistikleri doğal olarak değişebilir.
Bu kontrol tüm uygulama tablolarının/sütunlarının kapsamlı doğrulaması değildir.

Yalnız `[V6_SCHEMA_CHECK]` allowlist özetleri loglanır; ham stdout/stderr,
exception mesajı, DSN, adres, kullanıcı ve token loglanmaz. Hatalar: eksik
bağlantı, geçersiz yapılandırma/TLS, eksik dependency, authentication, yetki,
bağlantı/timeout, eksik database/schema/table, eksik migration/checksum farklılığı.
Bilinmeyen çıktı başarı sayılmaz. Eski yazma flag'i açıksa kontrol BLOCKED olur.
Hata web/worker'ı durdurmaz; başarı otomatik veri geçişine yetki vermez.

## Sonradan onaylanabilecek en küçük uygulama planı

1. Aktif production commit'i ayrıca doğrula. 67a7373 tabanı üzerine yalnız
   diagnostics modülleri, readonly checker ve başlatıcı hook'unu taşı. Geliştirme
   dalının diğer evren/tahmin değişikliklerini topluca merge/deploy etme.
2. Eski write-capable startup bloğunu devre dışı bırakacak minimal launcher
   farkı hazırlandı: `/tmp/V6_READONLY_STARTUP_67A.patch`. Bu patch uygulanmadı.
   Yeni modüller ve diagnostics değişiklikleri de release'e dahil edilmelidir.
3. Kullanıcı ayrıca deploy/restart onayı verirse kodu yayınla. Railway →
   bist-ai-bot → Variables içinde yeni flag'i 1 yap; Logs içinde güvenli
   SUCCESS/FAILED/BLOCKED sonucunu incele. Kontrol sonrası flag'i kaldır.
   Kullanıcıdan terminal komutu istenmez.
4. Şema başarısızsa dur; schema apply, migration veya STORAGE_BACKEND geçişi
   başlatma. Eksik şema sonucu yalnız eksikliği bildirir.

Bu plan şimdi uygulanmaz. Deploy/Variables güncellemesi restart gerektirebilir;
normal worker ve mevcut startup bakım kodu kendi yazımlarını sürdürebilir.
Dolayısıyla yalnız checker'ın salt okunur olması, tüm restart'ın `/data`
içeriğini hiç değiştirmeyeceği anlamına gelmez. Bu koşul mutlaksa mevcut canlı
sürümde deploy/restart olmadan, sağlayıcının read-only komut yürütme erişimi
sağlanıncaya kadar production kontrolü yapılamaz. Yeni servis, ücretli kaynak,
admin endpoint veya migration oluşturulmaz.
