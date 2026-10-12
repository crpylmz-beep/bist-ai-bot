# Migration öncesi koruma ve geri dönüş planı — uygulanmadı

Mevcut production SCHEMA_MIGRATION_REQUIRED/SCHEMA_VERIFY mesajı eski kontrolün
birden çok durumu birleştirdiğini kanıtlar; hangi nesnenin eksik olduğunu kanıtlamaz.
Railway araçları/kimlik bilgileri burada yoktur. Canlı schema, tablo ve metadata
kayıtları doğrulanmadı. Eksiklik varsayarak migration veya metadata tamiri yapılmaz.

## Yalnız teşhis

Hazırlanan ayrı dal, read-only transaction içerisinde yalnız SELECT to_regnamespace,
to_regclass ve metadata sorgusu kullanır. Yukarıdaki sabit kodlardan birini döndürür.
DDL/DML, schema repair, data import veya otomatik fallback yoktur. Bu dalı
incelemeden merge/deploy etme. Önceki startup yazma flag'i BLOCKED kalır;
yeni kontrol flag'i bu görev kapsamında değiştirilmez.

Kataloglardan tam nesne incelemesi için sonraki yetkili salt okunur oturumda
pg_namespace, pg_class, pg_index, pg_constraint, pg_attribute, pg_proc ve pg_trigger
SELECT sorguları manifest ile karşılaştırılmalıdır. Tablo içerikleri, kullanıcı
verileri veya bağlantı adresleri loglanmaz. Metadata checksum'unun doğru olması,
nesne drift'ini tek başına dışlamaz. Bu görev o production oturumunu gerçekleştirmedi.

## Migration için zorunlu önkoşullar

1. Ayrı production onayı, doğrulanmış aktif commit ve gerçek schema envanteri.
   STORAGE_BACKEND=legacy korunmalı; aynı anda çalışan başka schema yazıcısı olmamalı.
2. PostgreSQL'in sağlayıcı yedeği veya tutarlı mantıksal yedeği, gerekli roller ve
   yetkilerle güvenli, özel ve /data dışında bir hedefe alınmalı. Otomatik ücretli
   kaynak oluşturulmamalı; kapasite ve maliyet önceden doğrulanmalı. Şifre/DSN
   çıktılanmamalı. Mevcut veritabanı boş olduğu varsayılmamalı.
3. Yedek checksum'u, boyutu ve okunabilirliği doğrulanmalı; izole test veritabanında
   geri yükleme kanıtlanmalı. Yedek alınmış olması geri dönüşün kanıtı değildir.
4. /data ve V5 journal/recovery geçmişi korunmalı. UNKNOWN,
   UNIQUE_RECOVERY_CANDIDATE ve FINAL_LOCK_BUSY dosyaları değiştirilmemeli.
   Canlı dosyaların tutarlı yedeği için mevcut yazıcılarla koordinasyon ve onaylı
   snapshot gerekir; /data üzerinde büyük temp kopya üretilmemeli. İncelemeden
   hiçbir recovery kaydı kaynak dışı veya mükerrer kabul edilmemeli.
5. İlgili migration SQL/checksum'ları sabitlenmeli. Checksum uyuşmazlığı varsa dur;
   SQL geçmişini veya migration metadata checksum'unu eşleştirmek için değiştirme.
   SQL'de CREATE TRIGGER ve ALTER TABLE bulunduğundan elle uygulanmış kısmi şema
   veya yanlış metadata durumunda kör yeniden çalıştırma güvenli değildir.
6. Önce izole kopyada migration/geri dönüş provası, tablo ve PK/FK/indeks/immutable
   trigger doğrulaması; tahmin kimliği, kayıt sayısı, frozen hash, outcome/journal
   bütünlüğü karşılaştırması. Boş şema oluşturmak veri taşıma onayı değildir.
7. Onaylı production migration aşamasında yalnız bir operatör/yazıcı. Mevcut
   migrate() advisory lock ve transaction kullanır; hata halinde rollback ve
   tekrar salt okunur doğrulama yapılmalı. Doğrulanmamış kısmi duruma devam edilmemeli.
8. Geri dönüş: legacy uygulama/volume olduğu gibi korunur, eski doğrulanmış uygulama
   sürümüne dönüş ayrı deployment onayıyla yapılır. PostgreSQL'de destructive
   down-migration uygulanmaz. Yedekten restore ancak ayrı açık onay ve test edilmiş
   prosedürle; bu görev kapsamında uygulanmaz. Migration sonrası veri taşıma,
   shadow/postgres cutover ve STORAGE_BACKEND değişimi ayrıca onay gerektirir.

Bu aşamada yedek oluşturulmadı, migration çalıştırılmadı, production veya disk
kurtarma kayıtlarına erişilmedi. Kod ve offline mock testleri hazırlandı.
