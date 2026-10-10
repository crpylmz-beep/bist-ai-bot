# V6 PostgreSQL toplu aktarım – operasyon notu

## Durum
Bu dal canlıya dağıtılmamıştır. PostgreSQL'e veri aktarımı yapılmış sayılmaz.
Mevcut uygulama JSON /data üzerinden çalışmaya devam eder.

## Tek komut
Yalnızca /data diskinin bağlı olduğu BIST uygulaması konteynerinde ve PostgreSQL bağlantısı mevcutken:

```bash
python -B -m v6_storage.bulk_import --apply
```

Komut yalnızca desteklenen runtime JSON ve tarihli arşiv JSON kaynaklarını işler.
Desteklenmeyen private dosyalar, geçici dosyalar ve kurtarma kayıtları **taşınmış sayılmaz**;
orijinal /data içeriği korunmalıdır. Mevcut Migrator her kaynak için checksum,
değişim denetimi ve devam edilebilir PostgreSQL import kayıtlarını kullanır.
Kaynak canlı süreç tarafından değiştirilirse ilgili dosya UNRESOLVED kalabilir.

## Kesin sınırlar
- Bu komut veritabanı şemasını oluşturmaz; önceden hazır olması gerekir.
- Kaynak dosyaları silmez veya yeniden adlandırmaz.
- STORAGE_BACKEND değiştirmez; uygulamayı PostgreSQL'e geçirmez.
- Her kaynağın aktarım durumu Railway loglarından izlenmelidir.
- PARTIAL veya BLOCKED sonucu, başarılı tam geçiş anlamına gelmez.
- Tam veri envanteri, yedekleme ve doğrulanmış backend geçişi ayrıca gerekir.
- Railway pre-deploy aşamasında /data mount edilmez; bu komut orada çalıştırılamaz.

## Canlıya alma
Kod incelemesi ve üretim koşulları tamamlanmadan bu dalı main'e birleştirmeyin.
Bu dosya otomatik başlatma veya üretim ortamında değişiklik yapmaz.
