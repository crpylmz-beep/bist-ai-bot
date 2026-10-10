# V6 ilk şema kurulumu: teşhis ve güvenli hazırlık

Kaynak tabanı: 6481d9c97ff95a47028b3b65fdc99eba8b5a3b9f.
Production kullanıcı raporu: servisler ONLINE, deployment SUCCESS,
SCHEMA_NAMESPACE_MISSING / SCHEMA_VERIFY. Canlı bağlantı bu ortamda
bağımsız doğrulanmadı. Hiçbir production işlem uygulanmadı.

## Kesin anlam ve bilinmeyenler

ready(), READ ONLY transaction içinde SELECT to_regnamespace('bist_v6')
sorgusunun NULL olması halinde bu kodu verir. Bu, kullanılan bağlantının
veritabanında namespace yokluğu demektir; veritabanının tümü boş demek değildir.
Migration metadata sorgusu henüz çalışmaz. Başka şemalarda/veritabanlarında
veri veya başka PostgreSQL servislerinde V6 kayıtları bulunabilir. Yetki,
SQLSTATE veya bağlantı hataları bu kod yerine mevcut ayrı hata yollarına gider.

DATABASE_URL ve varsa BIST_POSTGRES_DSN seçimi kontrol edilmelidir; ikinci
birinciye önceliklidir. Hata override'ın yanlış olduğunu kanıtlamaz. Kullanıcı
geçmişinde birden fazla PostgreSQL servisi bulunduğundan servis eşleşmesi
kontrolü özellikle önemlidir. TLS require encryption sağlar; doğrulanmış CA ile
verify-full daha güçlüdür. Bu aşamada ayar değiştirilmez.

## Sonraki uygulanabilir salt okunur kontrol

Yetkili Railway araç erişimi sağlandığında terminal/SSH talep etmeden:

1. Production environment ve botun etkin deployment SHA'sını doğrula.
2. Botun seçtiği connection variable'ın referans ettiği PostgreSQL service ID'sini
   amaçlanan servisle güvenli oturum içinde karşılaştır. Yalnız değişken adı ve
   eşleşti/eşleşmedi/bilinmiyor raporla; DSN, database adı, kullanıcı, adres,
   port veya credential çıktılama. İki değişken varsa override varlığını bildir.
3. READ ONLY transaction ile current_database() sonucunu beklenen servis
   veritabanı kimliğiyle yalnız bellekte karşılaştır; yalnız boolean sonucu raporla.
   Sorgu sonucu veya connection URL'sini loglama. SQL NULL namespace kontrolünü
   pg_namespace/pg_class kataloglarının okunmasıyla doğrula.
4. Sadece bist_v6 beklenen nesnelerinin varlığı ve diğer şemalar/tablolara ilişkin
   toplam sayıları bildir. Başka şema/tablo adları veya içerikleri çıktılanmaz.
5. Metadata tablosu varsa bilinen dört migration adı/checksum'u karşılaştır.
   Yoksa SELECT metadata tablosu çalıştırma. SQL nesne varlığı manifest ile
   ayrı kontrol edilmeli; metadata eşleşmesi tam şema drift kontrolü değildir.
6. Beklenen DB eşleşmesi doğrulanamıyorsa veya yanlışsa DUR. Yeni schema
   oluşturma; connection değişikliği de ayrıca onaylı olmalı.

## İlk kurulumun ayrı onay gerektiren sırası — şimdi çalıştırılmaz

1. Doğru servis/veritabanı ve mevcut nesne envanteri doğrulanmış olmalı.
2. Mevcut PostgreSQL verisi (boş varsayılmadan) özel hedefe yedeklenmeli;
   checksum/kapasite/maliyet doğrulanmalı, izole geri yükleme provası yapılmalı.
   Yeni ücretli servis oluşturulmaz. Kaynak /data üzerinde temp kopya üretilmez.
3. /data, JSON/WAL, learning/prediction/outcome ve recovery bütünlüğü korunmalı.
   Tutarlı backup gerekiyorsa mevcut yazıcılarla koordinasyon ve ayrıca onay;
   FINAL_LOCK_BUSY, UNKNOWN, UNIQUE_RECOVERY_CANDIDATE kayıtlarına müdahale yok.
4. SQL dosyalarının manifest checksum'ları sabitlenmeli; aynı SQL izole restore
   üzerinde ayrı onayla denenmeli. PK/FK, indeks, immutable trigger ve kayıt
   bütünlüğü sınanmalı. Yanlış DB veya kısmi schema varsa kör kurulum yapılmaz.
5. Önkoşullar sağlanınca ayrıca production schema kurulum onayı alınmalı.
   Sadece PostgreSQL schema aşaması; legacy bot/volume korunur. Mevcut migrate()
   advisory lock ve tek transaction kullanır. Eski startup schema flag'i
   güvenlik nedeniyle BLOCKED olduğundan ilk kurulum için kullanılmaz.
6. Daha sonra salt okunur kontrol ile dört migration kaydı/checksum'u ve
   nesneler doğrulanır. Hata durumunda rollback; otomatik down-migration,
   DROP veya metadata düzeltmesi yapılmaz. Restore yalnız test edilmiş plan
   ve ayrı onayla. Bot legacy okumaya/yazmaya devam eder.
7. Schema kurulması JSON verisini taşımaz veya disk kurtarma işini çözmez.
   Veri import, shadow karşılaştırma ve backend geçişi ayrı aşamalardır;
   snapshot/frozen hash/outcome/journal kaydı doğrulanmadan cutover olmaz.

## Bu incelemedeki kanıt

- Main dört SQL migration checksum'u manifestle birebir eşleşti.
- 001 records.ordinal ekler; 004 import_proofs.ordinal ekler. Manifestte önceki
  002 atfı düzeltildi. SQL dosyaları ve uygulama kodu değiştirilmedi.
- Mevcut dokuz schema-reason offline testi tekrar geçti; production sorgusu
  çalıştırılmadı. Önceki 125 ilgili testin aynı kod tabanı korunuyor.
- Railway araç/credential ve PostgreSQL bağlantı bilgisi bu oturumda yoktur.
  Canlı schema, DB kimliği, tablolar ve backup durumu doğrulanmış değildir.
