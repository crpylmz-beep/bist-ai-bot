# V6 tek komut girişli güvenli taşıma — Issue #11

Bu araç hazırlanmış koddur; production üzerinde çalıştırılmış taşıma değildir.
`python -B -m v6_storage.tree_transfer` tek giriş noktasıdır. Varsayılanı
salt okunur DRY_RUN'dır; kaynak dosyaları, STORAGE_BACKEND, Railway ve şema
değişmez. Production çalıştırma/deploy ve her yazma aşaması ayrıca onay ister.
Hiçbir komut mevcut `bist_v6` şemasını oluşturmaz veya migration SQL'i çalıştırmaz.

## İşletim kapıları

1. Yetkili operatör ayrı, kalıcı, özel erişimli ve yeterli kapasiteli depolamayı
   hazırlar. Araç kaynak içinde veya `/data` altında yedek oluşturmayı reddeder;
   `/tmp` kalıcı yedek sayılmaz. `--durable-external-storage` operatörün mount ve
   dayanıklılık kontrolünü beyan eder; araç bulut volume oluşturmaz ve mount'un
   kalıcılığını kendi başına kanıtlayamaz. Workspace önceden oluşturulmuş, 0700
   olmalıdır. Aynı workspace için nonblocking operatör kilidi vardır.
2. Onaylı bakım penceresinde web/worker dahil tüm kaynak ve PostgreSQL yazıcıları
   durdurulur veya ayrıca doğrulanmış tutarlı salt okunur snapshot sağlanır.
   `--writers-quiescent` bu koşulun beyanıdır; araç çalışan servisi durdurmaz.
   Başlangıç/son SHA-256 ağaç eşitliği değişimi yakalar; bu, yazıcı durdurmanın
   yerine geçmez. Değişmiş ağaçla eski checkpoint'e devam edilmez.
3. DATABASE_URL/BIST_POSTGRES_DSN yalnız ortamdan alınır; TLS korunur. Ayrı,
   boş restore veritabanı `V6_RESTORE_DSN` ve `V6_RESTORE_ISOLATED=1` ile
   tanımlanır. Yetkili operatör DNS alias'ları dahil bunun production'dan farklı
   sunucu/veritabanı olduğunu ve rolünün yalnız izole hedefe eriştiğini doğrular.
   URL karşılaştırması tek başına bu güvencenin yerine geçmez.
4. `pg_dump`/`pg_restore` sürümleri sunucuyla uyumlu olmalı; özel schema objeleri,
   extension, roller, izinler ve sequences ayrıca kontrol edilmelidir. Araç tablo
   satırları/sayıları ve sütun tanımlarını karşılaştırır; her SQL nesnesini veya
   uygulama davranışını kanıtlamaz. Cutover hiçbir koşulda otomatik değildir.

## Aynı giriş noktası, ayrı onaylanan aşamalar

Salt okunur plan; hiçbir istemci açılmaz ve checkpoint yazılmaz:

```sh
python -B -m v6_storage.tree_transfer --root /data
```

**Önerilen, burada çalıştırılmamış production komutları:** onaylı bakım koşulları
ve hazır harici mount/izole DB olmadan aşağıdaki `--apply` komutları çalıştırılmaz.

```sh
python -B -m v6_storage.tree_transfer --root /data --workspace /private-backup/v6-job --phase prepare --apply --writers-quiescent --durable-external-storage
```

Prepare bütün normal dosyaları (temp, recovery, unknown dahil) harici `backup/`
ağacına 1 MiB parçalarla kopyalar, ayrı `rehearsal/` ağacına geri yükleme provası
yapar; kaynak, yedek ve prova dosya yolları/sayıları/SHA-256 değerlerini eşler.
Boş dizinler korunur. Link/özel dosya varsa işlem UNRESOLVED ile kapanır;
hiçbiri silinmez veya izlenerek dışarıya açılmaz. Dosya izinleri yedekte özel
0700/0600 olur; kaynak owner/ACL/mtime geri yükleme aracı değildir.

Ardından ayrı tutarlı `pg_dump --format=custom` yedeği alınır ve yalnız önceden
doğrulanmış boş izole DB'ye transaction içindeki restore provası yapılır.
`pg_restore --list` tek başına başarı sayılmaz. PostgreSQL tablo içeriklerinin
SHA-256 satır özetleri (sayı, toplamsal ve XOR özetleri) ile sütun envanteri
karşılaştırılır. Bu özetler olasılıksal bütünlük kontrolüdür; sequence/rol/trigger
eşitliği ve gerçek uygulama restore testi ayrıca gereklidir. Bağlantı URL'leri
argv/log'a çıkmaz. Client stderr gizlidir; kontrollü hata kodları raporlanır.

Kapasite kontrolü harici alanda iki tam dosya ağacı + 64 MiB pay, ayrıca dump
öncesi iki kat PostgreSQL boyutu + 64 MiB pay ister. Kaynak diske ikinci kopya
yazılmaz. İzole DB'nin kendi disk kapasitesi operatör tarafından doğrulanır.
Metadata manifest/checkpoint en çok 16 MiB, ağaç bütçesi en çok 10.000 girdidir.

Prepare tamamlandıktan sonra, ayrı aktarım onayıyla:

```sh
python -B -m v6_storage.tree_transfer --root /data --workspace /private-backup/v6-job --phase import --apply --writers-quiescent --durable-external-storage --budget-records 10000
```

Import canlı yazıcı dosyalarını değil doğrulanmış `rehearsal/` kopyalarını okur.
Gerçek dataset/model kimlikleri korunur. Şema hazır olmalıdır. Desteklenen
koleksiyonlar önce salt okunur preflight'tan geçer, sonra mevcut conservative
Migrator ile en fazla 100 kayıtlık transaction'larda yazılır. Çakışmalar korunur;
sonrasında kimlik, sayı ve reconstructed kayıt SHA-256 eşitliği SELECT/READ ONLY
ile doğrulanır. Dosya başına varsayılan 100.000 kayıt sınırı (açıkça en fazla
1.000.000 yapılabilir) bellek/kimlik setini sınırlar. JSON bozukluğu, duplicate
ID, limit veya eksik kayıt gerçek UNRESOLVED nedenidir; eksik ID uydurulmaz.

`--budget-records` tur başına **dosya için** iş bütçesidir; BUDGET_EXHAUSTED
durumunda aynı komut yeniden çalıştırılır. PostgreSQL receipt cursor'ları
transaction ile kayıtlarla birlikte commit edilir; tamamlanan dosyalar tekrar
doğrulanır, aynı kayda mükerrer insert yapılmaz. Checkpoint sadece harici
workspace'tedir, en fazla bir küçük `.next` dosyası vardır. Kısmi dosya kopyası
yalnız SHA-256 kaynak ve kaydedilmiş prefix eşleşiyorsa append ile sürer.
Çakışan/kısmi PostgreSQL dump korunur; otomatik silinmez veya üzerine yazılmaz.
Restore kesilirse hedef boşsa güvenli yeniden deneme, doluysa salt okunur
eşitlik kontrolü yapılır; başarısız/different restore manuel inceleme gerektirir.

Desteklenmeyen dosyalar (özel kullanıcı verileri, WAL/journal, temp/unknown dahil)
yedekte kalır; private manifest'te gerekçeyle UNRESOLVED raporlanır. Kod bunları
PG kayıtlarına uydurmaz, recovery journal'ı yeniden yazmaz, UNKNOWN veya
UNIQUE_RECOVERY_CANDIDATE dosyasını temizlemez. Tek bir dosyanın eşitlik kontrolü
bütün kaynağın taşındığı anlamına gelmez. UNRESOLVED varsa “her şey taşındı” denmez.

## Çıktı ve geri dönüş

`[V6_TRANSFER]` yalnız kategori sayısı/byte, aşama, ilerleme ve sabit hata kodu
gösterir. Private manifest dosya yollarını içerdiğinden paylaşılmaz; dosya
içeriği/kişisel kayıt/DSN rapora basılmaz. DRY_RUN ve hazır yedek durumunda exit 0;
UNRESOLVED, bütçe veya guard hatasında exit 2. PostgreSQL yeni servis veya R2
bucket oluşturulmaz; ücretli kaynak provisioning'i yoktur.

Rollback: kaynak `/data` ve legacy backend değişmediği için uygulama legacy'de
çalışmayı sürdürür. Bu komut PG'yi geri almaz, DROP/DELETE çalıştırmaz. Başarısız
import receipt/çatışmaları ve harici yedekleri korur. Gerçek cutover ancak bütün
UNRESOLVED kaynaklar çözüldükten, tam yedek/restore ve uygulama regresyonu gerçek
ortamda kanıtlandıktan sonra ayrı plan/onayla yapılır. Bu geliştirmede production
erişimi, gerçek yedek, restore, veri taşıma veya deploy yapılmamıştır.
