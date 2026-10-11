# PostgreSQL V6 salt okunur taşıma doğrulaması

Bu araç veri taşımaz, import receipt yazmaz, `ready/migrate` çağırmaz, kaynak
dosya oluşturmaz ve backend/servis ayarı değiştirmez. Başlangıç mekanizmasına
bağlı değildir; mevcut bulk import'u durdurmaz veya yeniden başlatmaz.

## Ölçüm ve kapsam

`readonly_json_census.py` kategorileri ve dosya sınıflandırması kullanılır;
onun array/object/JSONL sayıları **mantıksal kayıt sayısı değildir**. Yalnız
`records.shape_for` tarafından gerçekten desteklenen koleksiyonların kayıtları
streaming okunur. Başlık, kriter dizileri ve nested sonuçlar ayrı tahmin sayılmaz.
Kimlik için importer ile aynı `row_key` kullanılır: açık kayıt ID'si, doğrulanmış
mapping anahtarı, tarihli snapshot sembol kimliği veya yalnız mevcut adapter'ın
izin verdiği learning alt koleksiyonunda kanonik içerik kimliği. Eksik ID
uydurulmaz; desteklenmeyen JSON/JSONL ve dosyalar INCONCLUSIVE nedenidir.

Tekil birim `dataset + collection + record_id`'dir; bu PostgreSQL'in gerçek
anahtar kapsamıdır. Aynı koleksiyondaki aynı ID/aynı içerik bir kez sayılır,
duplicate sayısı ayrı tutulur. Aynı ID/farklı içerik çakışmadır. BASE/LEARNED
gibi ayrı model koleksiyonları farklı kayıt bağlamlarıdır; model bağlamları
arasında kimlik birleştirerek sahte tekilleştirme yapılmaz. Bu nedenle rapor
"bütün uygulamada bağlamdan bağımsız tekil olay sayısı" iddiasında değildir.

Hedef tablolar `bist_v6.records`, `record_extensions`, `row_states`, `outcomes`.
Sonuç/state/extension kayıtları yeni tahmin olarak sayılmaz; mevcut `assemble`
ile orijinal kayıt tekrar kurulur. Kaynak SHA-256, reconstructed hedef SHA-256,
hedef frozen_hash ve current_hash birlikte eşleşmelidir. Import status=VERIFIED
veya bulk logu tek başına taşıma kanıtı olarak kullanılmaz. PostgreSQL sayıları
tek REPEATABLE READ, READ ONLY transaction'da alınır; devam eden importer bu
ölçüm snapshot'ına sonradan görünmez. Rapor işlem anını temsil eder.

PostgreSQL toplam/tekil sayıları desteklenen dataset/koleksiyonların tümünü
kapsar; kaynağa eşleşmeyen diğer dataset'ler yalnız `pg_unclassified_records`
toplamında gösterilir. PostgreSQL'de daha eski/ek kayıtlar olması kaynak
kayıtlarının %100 eşleşmesini engellemez; hedef toplamı kaynak toplamına eşit
olmak zorunda değildir. Kaynak kaydı eksik veya farklıysa ayrı sayaçtır.

## Durumlar

- VERIFIED: tutarlı kaynak snapshot'ı ayrıca doğrulanmış ve beyan edilmiş,
  kaynak/DB taramaları tamamlanmış, bütün tekil kaynak kayıtları içerikleriyle
  eşleşmiş, belirsiz/unsupported/kimliksiz/çakışmalı/okunamayan kayıt yoktur.
- PARTIAL: güvenilir payda var, kayıtların bir bölümü eksik/uyuşmuyor.
- NOT_STARTED: güvenilir payda var, hiçbir kaynak ID'si hedefte bulunmuyor.
  Tüm ID'ler mevcut fakat içerikleri yanlışsa bu durum PARTIAL'dır.
- INCONCLUSIVE: kaynak snapshot güvencesi yok, dosya değişti, kayıt kimliği
  bilinmiyor, dosya bozuk/unsupported veya bütçe bitti. Payda tam değilse
  `progress_percent=null`; kısmi kaynak sayıları alt sınırdır.
- FAILED: bağlantı veya hedef şema/tablo kontrolü başarısız. DB sayıları `null`;
  hata mesajı yerine sabit, gizli bilgi içermeyen hata kodu gösterilir.

Okunamayan **dosyaların** sayısı bilinir; içlerindeki mantıksal kayıt sayısı
kanıtlanamayacağı için `unreadable_records=null` olur. Sıfır kayıt boşluğundan
VERIFIED üretilmez. `source_counts_complete` ve `database_counts_complete`
alanları sayımların tam olup olmadığını açıklar. Yüzde, doğrulanan tekil kaynak
/ tekil kaynak × 100'dür; farklı içerik veya unknown kayıt başarı sayılmaz.

## Sınırlar ve gizlilik

Varsayılan bütçeler: 300 saniye, 10.000 dosya/girdi, 100.000 mantıksal kayıt,
1 GiB okunan veri, sorgu başına en fazla 100 ID. ID/checksum seti kayıt bütçesiyle
sınırlıdır; bütün kaynak geçmişi belleğe alınmaz. JSON token/kayıt limiti 8 MiB,
derinlik 64; büyük atomik string'ler de reader seviyesinde durdurulur.
Hedef batch okunmadan dört tablonun açılmış JSON metni toplam byte/satır sayısı
SELECT ile kontrol edilir; 16 MiB veya 10.000 satır sınırını aşan batch yüklenmez.
Süre kontrolü parsing, keşif ve her `_rows` SELECT'i öncesinde uygulanır; statement
timeout transaction içidir. Bağlantı/pool timeout'u mevcut güvenli ayarlardadır.
Kesilen tarama başarılı ilan edilmez; bütçeler yalnız onaylı kaynak boyutlarına
göre artırılmalıdır. Hiçbir disk checkpoint/temp/log dosyası yaratılmaz.

`[V6_MIGRATION_VERIFY]` JSON raporu yalnız kategori sayaçları, toplu kaynak
özeti ve sabit kodları içerir. Dosya yolu, tekil ID, kişi verisi, haber içeriği,
DSN/şifre basılmaz. PostgreSQL pool logları mevcut güvenli filtreyi kullanır.
Okuma filesystem atime davranışını etkileyebilir; içerik/yazma/migration yoktur.

## Production için yalnız öneri — burada çalıştırılmadı

```sh
python -B -m v6_storage.migration_verify --root /data --max-seconds 300 --max-records 100000
```

Bu canlı gözlemde eşleşmeleri gösterir fakat snapshot güvencesi olmadığından
tamamlanma ilan etmez. Production'da çalıştırmak için ayrıca kullanıcı onayı ve
mevcut process'e güvenli komut erişimi gerekir; bu geliştirme deploy içermez.

Ayrıca doğrulanmış, bütün ilgili `/data` ağacını kapsayan salt okunur tutarlı
snapshot mevcutsa onun kökü `--root` verilerek `--consistent-source-snapshot`
kullanılabilir. Flag snapshot oluşturmaz, writer durdurmaz; beyanın gerçek
altyapı kanıtıyla doğrulanması operatör sorumluluğudur. Yeni snapshot/backup,
deploy veya ayar değişiklikleri bu görevin otomatik adımı değildir.

PostgreSQL'de SELECT yetkili rol önerilir. Bu araç write-capable mevcut
`bulk_import --apply`, `schema` veya legacy startup import flag'lerini çağırmaz.
Sonuç VERIFIED olsa dahi otomatik cutover/silme yapılmaz. Gerçek Railway kayıt
sayıları, erişim olmadığı durumda bu dokümanda verilmez.
