# V6 taşıma güvenlik araçları — production'da çalıştırılmadı

Bu dal yalnız PostgreSQL geçişine aittir. Schema kurulumu, legacy backend,
/data, recovery dosyaları ve TOP10 algoritmalarına dokunmaz.

## Komutlar

Salt okunur dosya sayısı/boyutu, kategoriler, JSON/sıkıştırılmış veri türleri,
checksum ve disk kapasitesi:

`python -B -m v6_storage.migration_safety inventory --root /data`

Envanter metadata, bütünlük kontrolü streaming içerik okur; içerik/yol/secret
çıktılamaz. Kaynak değişirse INCOMPLETE; canlı scan tutarlı snapshot garantisi
vermez. Unknown/recovery dosyaları korunur, envanter taşınabilir ilan etmez.

Özel /data dışı ve yeterli kapasitede hedefe PostgreSQL yedek hazırlığı:

`python -B -m v6_storage.migration_safety backup /private-backups/bist.dump`

Varsayılan DRY_RUN; sadece ayrıca yetkilendirilmiş yedek alma için `--apply`.
pg_dump custom format ve tek tutarlı snapshot kullanır. Dış hedefin kapasite,
yedek erişim gizliliği ve pg_dump/pg_restore sürüm uyumu operatörce doğrulanmalı.
Özel yeni dosya 0600 oluşturulur, var olan hedef overwrite edilmez. Hata halinde
kısmi dosya korunur, yedek kabul edilmez. Credential subprocess environment ile
geçer, argv/loglara yazılmaz. Production ortamında bu görev yedek almadı.

`python -B -m v6_storage.migration_safety inspect-backup /private-backups/bist.dump --sha256 <DOĞRULANMIŞ_SHA256>`

Streaming hash ve pg_restore --list; restore çalıştırmaz. Başka güvenilir
kanaldan alınan SHA-256 gerekir; mevcut dosyanın hash'ini kendisiyle kıyaslamak
önceki yedeğin doğrulandığı anlamına gelmez. Başarı restore_verified=false kalır.

`python -B -m v6_storage.migration_safety restore-rehearsal /private-backups/bist.dump --sha256 <DOĞRULANMIŞ_SHA256>`

Varsayılan DRY_RUN. Gerçek provaya ayrıca onay, `--apply`, V6_RESTORE_ISOLATED=1
ve güvenli environment üzerinden V6_RESTORE_DSN gerekir. Production DSN
(BIST_POSTGRES_DSN > DATABASE_URL) ile host/port/database eşleşmesi yasaktır.
Kataloglar readonly kontrol edilerek dolu hedef reddedilir; restore tek transaction
ve hata halinde rollback ister, --clean/create yoktur. Farklı DNS alias'ları
aynı production'a işaret edebilir: otomatik karşılaştırma tek başına izolasyon
kanıtı değildir. Ayrı sunucu/servis, yalnız o test DB'ye yetkili credential ve
başka yazıcı bulunmadığı operatörce doğrulanmadan --apply kullanılmamalıdır.
Archive SQL güvenilir kaynaktan gelmeli. Araç servis oluşturmaz, maliyet eklemez.
Restore başarılı olsa bile restore_verified=false: aşağıdaki kayıt eşitliği,
şema/rol/constraint/trigger ve yedek nesne kapsamı incelemesi ayrıca gerekir.

JSON/DB kayıt karşılaştırması (SELECT-only, bounded batches):

`python -B -m v6_storage.migration_safety compare /data/runtime/ai_ogrenme_gecmisi.json --batch-size 100 --max-records 100000`

BIST_DATA_DIR source modelini belirler. DSN doğrulanacak DB'yi gösterir;
production veya izole restore hedefi ayrı yetkili süreçte seçilir, Railway
variables/STORAGE_BACKEND otomatik değiştirilmez. Bilinmeyen dosya veya recovery
kaynağı SOURCE_SCHEMA_UNSUPPORTED_RECOVERY_PRESERVED olarak durur.

Tek REPEATABLE READ, READ ONLY transaction; belge metadata/collection eşitliği,
source ID'leri, DB'de eksik/ekstra ID sayısı, yeniden oluşturulmuş record checksum,
frozen/current hash kontrol edilir. Eksik ve ekstra kimlikler aynı count'ta da
ayrı bulunur. İçerik/kimlikleri çıktılamaz; sadece sayılar ve sabit hata kodları.
BUDGET_EXHAUSTED başarı sayılmaz; doğrulama tekrar başlar, migration cursor'u
ayrı mevcut import araçlarında tutulur. Kayıt sırası/projection, import proof,
recovery journal ve tüm DB index/constraint varlığını tek başına doğrulamaz.
Büyük dosyalar streaming; batch <=1000, max_records <=1 milyon, görülen ID seti
budget ile sınırlıdır. Canlı source değişirse sonuç geçersizdir; doğrulanmış
snapshot olmadan cutover için kullanılmaz.

## Dış ortamda doğrulanacak

Gerçek PostgreSQL dump, bağımsız checksum, tam kapsam/roller, izole restore,
production dataset eşitliği, recovery çözüm durumu, tutarlı /data yedeği,
yeterli dış disk, DB servis kimliği, PostgreSQL sürümleri ve yetkiler.

Önceki şema kurulumunu tekrarlama. Gerçek import için ayrıca kullanıcı onayı,
yedek/geri yükleme ve bütünlük kanıtı gerekir. Mevcut migration dry-run,
idempotency, bütçe sonrası cursor devamı ve conflict-preserving davranışları
fake store/geçici dosyalarla sınanır. Bu offline sonuçlar production kanıtı değildir.
