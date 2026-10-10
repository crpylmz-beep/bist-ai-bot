# V6 bağlantı altyapısı ve kontrollü geçiş

Bu sürüm hiçbir kaynak oluşturmaz, veri taşımaz, kaynak silmez, şema uygulamaz
ve production depolama modunu değiştirmez. `STORAGE_BACKEND=legacy` varsayılanı
korunur. Yeni bağlantı bilgileri bulunmadığında uygulama mevcut JSON/V5 koruma
mekanizmalarıyla çalışır. Tanı aracı worker scheduler'ına veya public API'ye bağlı
değildir; otomatik probe yoktur. Bu geliştirmede canlı bağlantı denenmemiştir.

## Yapılandırma

Bilgiler yalnız güvenli ortam değişkenlerinden alınır; .env/secrets commit edilmez.

| Değişken | Amaç |
| --- | --- |
| `BIST_POSTGRES_DSN` veya `DATABASE_URL` | PostgreSQL DSN; birincisi önceliklidir |
| `STORAGE_TIMEOUT_SECONDS` | PG bağlantı/sorgu sınırı: 1–30 saniye, varsayılan 10 |
| `STORAGE_POOL_SIZE` | Mevcut uygulama havuzu: 1–8 bağlantı, varsayılan 4 |
| `STORAGE_BATCH_SIZE` | Mevcut yazım batch'i: 1–1000 kayıt, varsayılan 100 |
| `R2_ENDPOINT_URL` | HTTPS Cloudflare hesabı S3 endpoint'i |
| `R2_BUCKET` | Önceden operatör tarafından hazırlanmış özel bucket |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Bucket kapsamlı kimlik bilgileri |
| `R2_PRIVATE_BUCKET_CONFIRMED=true` | Operatörün özel erişim incelemesi onayı |
| `R2_CONNECT_TIMEOUT_SECONDS` | 1–60 saniye, varsayılan 10 |
| `R2_READ_TIMEOUT_SECONDS` | 1–60 saniye, varsayılan 30 |

Uzak PG URL’sinde `sslmode` yoksa bağlantı sırasında bellekte `sslmode=require`
eklenir; environment ve kaydedilmiş URL değişmez. Açıkça belirtilen tek bir
`sslmode=require`, `verify-ca` veya `verify-full` korunur;
çelişkili/tekrarlanan sslmode kabul edilmez. Tercihen sağlayıcının CA doğrulamasıyla
`verify-full` kullanın. R2 endpoint'i yalnız HTTPS Cloudflare R2 alanı kabul eder;
URL içindeki credential/query/fragment reddedilir. Özel bucket onay bayrağı gerçek
public erişimi teknik olarak doğrulamaz: r2.dev/custom domain erişimini ve policy'yi
operatör ayrıca incelemelidir. Hiçbir secret/DSN/endpoint çıktı veya repr'e konmaz.

## Salt okunur sağlık kontrolleri

```sh
python -B -m v6_storage connections-health
```

Varsayılan yalnız yapılandırmayı inceler, ağ bağlantısı açmaz. Durumlar:
`NOT_CONFIGURED`, `PARTIALLY_CONFIGURED`, `CONFIGURED_UNCHECKED`, `ERROR`.
İsteğe bağlı tanı (yalnız hazır kaynaklar ve bağlantılar için manuel):

```sh
python -B -m v6_storage connections-health --probe
```

PG tek kısa ömürlü bağlantıyla read-only transaction ve sınırlı `SELECT 1` yapar;
şema migration/readiness çağırmaz. Uygulamanın mevcut pooled writer'ını değiştirmez.
R2 yalnız `HeadBucket` yapar; list/get/put/delete veya create yoktur. Var olmayan
bağlantılarda probe da istemci açmaz. İki servis bağımsız raporlanır; birinin hatası
diğer kontrolü engellemez. İstemciler kapatılır. Hatalar yalnız sabit güvenli kodla
raporlanır; exception metni/traceback veya anahtarlar yazılmaz. SDK'nin mevcut R2
sınırlı retry/timeout davranışı korunur; sonsuz deneme veya yeni background retry
oluşturulmaz. CLI hata/kısmi yapılandırmada exit 2, diğer durumlarda exit 0 döner.
`OK` yalnız bağlantı erişimidir: yazma yetkisini, şema uyumunu, backup bütünlüğünü
veya geçişin güvenli olduğunu kanıtlamaz. `NOT_CONFIGURED` kesinti anlamına gelmez.

## Geçiş kapıları — şimdi uygulanmayacak

1. Salt okunur inventory alın; tahmin, learning, sonuç, journal, WAL ve recovery
   kayıtlarını ayrı sayın. UNKNOWN/UNIQUE_RECOVERY_CANDIDATE/unresolved kaydı koruyun;
   yeniden üretilebilir olduğu kanıtlanmadan hiçbir dosyayı cache saymayın.
2. Güncel fiyat, kapasite, yedekleme/egress maliyeti ve aylık ek 10 USD bütçeyi
   doğrulayın. Kaynak oluşturmak veya ücretli kapasite açmak ayrıca onay gerektirir.
3. Önce izole test ortamında PG schema/checksum/immutable tahmin-result ayrımını ve
   R2 stream/checksum/read-back/private erişimi doğrulayın. Production kaynakları
   ve `/data` değişmeden kalır; şema uygulaması ayrı yetkili işlemdir.
4. Mevcut migration dry-run ile sınıflandırma ve çakışma raporu hazırlayın; çözülmemiş
   recovery kayıtlarını exclude ederek kaybolmuş gibi kabul etmeyin. Her kaynağın
   checksum, kimlik ve kayıt sayısını manifestte doğrulamak geçiş önkoşuludur.
5. Ancak açık ayrı yetki sonrasında küçük resumable/idempotent transfer batch'leri
   ve doğrulanmış R2 yedekleri düşünülebilir. Kaynaklar hiçbir aşamada otomatik silinmez.
6. `shadow` karşılaştırması da dış depoya yazabilir; bu aşamada otomatik açılmaz.
   Mutabakat ve çakışma raporu temiz olmadan production cutover yoktur.
7. `postgres` ve `STORAGE_POSTGRES_CUTOVER_ACK` yalnız ayrı manuel cutover onayından
   sonra değerlendirilecek. Rollback için cutover sonrası yeni benzersiz kayıtların
   legacy'ye eksiksiz/çakışmasız geri alınması doğrulanmalıdır; sadece env değiştirmek
   veri kayıpsız geri dönüş kanıtı değildir. V5 journal ve recovery koruması korunur.

Bu hazırlık, `/data` kullanımının azaldığı veya canlı bağlantıların hazır olduğu
anlamına gelmez. Mevcut iş algoritmaları ve başlangıç varsayılanları korunmuştur.

TLS desteklemeyen sunucuya plaintext fallback yapılmaz. `require` şifrelemeyi
zorunlu tutar; sertifika/hostname doğrulaması için sağlayıcının CA yapılandırmasıyla
`verify-full` tercih edilmelidir. Bu düzeltme production bağlantısı veya migration
onayı değildir. Yerel loopback testlerinin önceki davranışı korunur.
