# V6 şema hatası incelemesi

Production için kesin kök neden henüz doğrulanmamıştır. Bu geliştirme ortamında
Railway aracı/CLI, Railway kimlik bilgisi ve production PostgreSQL bağlantısı yoktur.
Main SHA `67a7373ac5002965f2de69011ae5c089af6c1135` üzerinden şema komutu,
başlatıcı, ayarlar ve bağımlılık listesi salt okunur incelenmiştir.
`V6_SCHEMA_ONCE_RESULT FAILED exit_code=2` tek başına bir neden belirtmez.
Main başlatıcısı JSON `error` alanını `error_code` olarak loglayabilir.

Doğrulanan tanı eksikliği: transaction gerçek PostgreSQL hatasını genel
`POSTGRES_OPERATION_FAILED` koduna indirger. Alt süreç stderr çıktısı güvenlik
nedeniyle başlatıcı tarafından loglanmadığından, SQLSTATE ayrımı kaybolur.
Düzeltme yalnız sabit güvenli kodları ve doğrulanmış SQLSTATE alanını taşır;
hata mesajı, DSN, kullanıcı adı, parola veya traceback içeriğini göstermez.
Bağlantı, kimlik doğrulama, yetki, SQL, disk ve timeout hataları ayrılır.
CLI JSON error alanı güvenli ayrıntı kodunu kullanır; mevcut main başlatıcısı
bu alanı okuyabilir. Şema uygulama sonrasında checksum doğrulaması zorunludur.

Salt okunur doğrulama komutu:

```
python -B -m v6_storage schema --check
```

Bu komut yalnız migration tablosunu ve checksum değerlerini okur; DDL,
veri taşıma, volume yazımı veya STORAGE_BACKEND değişikliği yapmaz.
Şema yoksa/eksikse başarı sayılmaz. `schema` (check olmadan) mevcut explicit
DDL komutudur; production'da bu çalışma kapsamında çalıştırılmamıştır.

Aynı exit code yerelde ayrı ayrı şu durumlarla yeniden üretildi: bağlantı
bilgisi yok, uzak DSN'de TLS modu yok, dependency eksik, bağlantı hatası,
yetki/auth/SQL/disk SQLSTATE hataları. Bunlar production nedeni olarak
sunulamaz. Mevcut bağımlılık sürümleri requirements ile eşleşmektedir.
BIST_POSTGRES_DSN, DATABASE_URL'den önceliklidir; TLS koruması kaldırılmamıştır.
Eksik sslmode otomatik eklenmez, secret veya bağlantı ayarı değiştirilmez.

Sonraki gereken kanıt mevcut production kaydının güvenli `error_code` alanıdır.
Bu alan yoksa yalnız `exit_code=2` ile kesin neden çıkarılamaz. Şema başarıyla
ve gerçek PostgreSQL üzerinde doğrulanmadan veri aktarımı yapılmamalıdır.
Bu branch main'e merge edilmemiş, push/deploy yapılmamış ve /data'ya erişmemiştir.

## Bu branch'teki ek doğrulamalar

`PostgresStore.ready()` işlem başında `SET TRANSACTION READ ONLY` uygular.
Protokol stub testi gerçek ready metodunu çalıştırır; bu komut ve iki SELECT
haricindeki her SQL ifadesini reddeder. Bu offline testtir, production
PostgreSQL üzerinde çalıştırılmış bir test değildir. `schema --check` migrate
çağırmaz. Başarı sonucu yalnız checksum doğrulaması tamamlanınca verilir.
Ham psycopg.pool bağlantı uyarıları CLI şema sürecinde filtrelenir; yalnız
sabit hata kodları ve bilinen SQLSTATE sınıfları tutulur. Pool timeout'un
arkasındaki gerçek auth SQLSTATE bilgisi varsa bu güvenli kod korunur.
Filtre işlem tamamlanınca kaldırılır. Secret içeren örnek mesajlar stdout,
stderr ve log kontrolüyle sınanır; beş harfli rastgele SQLSTATE taklidi
(`TOKEN`) loglanmaz.

Mevcut production sürümünün SHA'sı ve geçmiş logları erişilebilir değildir.
Public /health isteği bu ortamda ProxyError vermiştir. Doğrulanabilen GitHub
main kodunda başlatıcı `status`, `exit_code`, `error_code` alanlarını üretir;
CLI `error` alanı okunur, `reason`, `stage`, `sqlstate` alanları başlatıcı
özetine aktarılmaz. Bunu çalışan deployment'ın kesin sürümü veya eski logda
bulunan bir hata kodu olarak sunmuyoruz. Yeni CLI özel güvenli nedeni `error`
alanına taşır, böylece bu başlatıcı ile uyumludur.
