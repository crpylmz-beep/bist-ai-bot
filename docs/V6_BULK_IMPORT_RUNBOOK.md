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

## Telefondan yönetilen Railway başlatma (opt-in)
Bu dalda `cloud_baslat.py`, web ve worker başlatıldıktan sonra
`BIST_RUN_POSTGRES_BULK_IMPORT_ONCE=1` ise aktarımı ayrı bir alt süreçte başlatır.
Varsayılan durumda **çalışmaz**. İşlem sonucu Railway loglarında
`[V6_BULK_IMPORT_LAUNCH]` ve `{"status":"DONE"}` veya `{"status":"PARTIAL"}`
satırlarıyla takip edilir. `started` yalnızca alt sürecin başlatıldığını
gösterir; başarılı aktarım anlamına gelmez.

**Önemli:** Ortam değişkeni etkin kaldıkça her yeni konteyner başlangıcında
tekrar çalışabilir. Sonuç doğrulanınca değişken kapatılmalıdır.
İşlem durursa PostgreSQL import cursor kayıtları sayesinde tekrar denenebilir.
Canlı JSON değişirse `SOURCE_CHANGED` ile çözümlenmemiş kalabilir.
Bu yöntem tüm /data içeriğini değil, yalnız desteklenen kaynakları kapsar.
