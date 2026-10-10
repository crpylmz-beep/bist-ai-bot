# V6 migration manifest — source 8575ee5

Bu manifest kaynak SQL dosyalarından üretilmiştir; canlı veritabanı envanteri değildir.

| Migration | SHA-256 |
|---|---|
| `001_core.sql` | `5b26360498fa5664679dd8fed3eac5ad4256a31d578959f9c6f699bcb53ec67c` |
| `002_import_proof.sql` | `d8aa162df70a710b3f91ec37998c929de6f62a752ea1ff0bb629d4c94ec44212` |
| `003_dataset_revision.sql` | `82cfc2f7d50964c03a583941d5b0b818350c72279964ce2e1eb099942f5a9427` |
| `004_current_projection.sql` | `7699cd27a56eb369a9659d217ac587f3dacf2981c6168748913b6547d0259241` |

## Beklenen nesneler

`bist_v6` şeması ve `schema_migrations` metadata tablosu `migrate()` tarafından SQL dosyalarından önce oluşturulur. Metadata sütunları: version (PK), checksum, applied_at (timestamptz). Migration kimliği tam SQL dosya adıdır.

### 001_core.sql

Tablolar: `bist_v6.symbols`, `bist_v6.data_sources`, `bist_v6.documents`, `bist_v6.records`, `bist_v6.record_extensions`, `bist_v6.row_states`, `bist_v6.outcomes`, `bist_v6.conflicts`, `bist_v6.import_sources`, `bist_v6.import_receipts`, `bist_v6.outbox_receipts`, `bist_v6.job_states`, `bist_v6.task_errors`, `bist_v6.archives`, `bist_v6.storage_usage`, `bist_v6.record_quality`.
Açık indeksler: `records_symbol_time`, `records_kind_time`, `outcomes_horizon`, `records_order`.
Fonksiyonlar: `bist_v6.immutable_row`, `bist_v6.freeze_record`.
Immutable trigger’lar: `records_frozen`, `outcomes_frozen`, `extensions_frozen`.

### 002_import_proof.sql

Tablolar: `bist_v6.import_conflicts`, `bist_v6.import_proofs`.

### 003_dataset_revision.sql

Tablolar: `bist_v6.dataset_versions`.

### 004_current_projection.sql

Tablolar: `bist_v6.document_projections`.

Her tablonun PRIMARY KEY tanımı ayrıca PostgreSQL benzersiz indeks oluşturur. 002 ordinal sütununu records’a, 004 ordinal sütununu import_proofs’a ekler. Şema kontrolü migration metadata ve dosya checksum’larını doğrular; tablo/sütun/trigger varlığının tam incelemesi değildir. Bu kapsam başarı logunda varsayılmamalıdır.

## Güvenli hata ayrımı

- SCHEMA_NAMESPACE_MISSING: bist_v6 namespace yok.
- SCHEMA_METADATA_MISSING: namespace var, schema_migrations yok.
- SCHEMA_MIGRATION_VERSION_MISSING: metadata var, beklenen dosyalardan en az birinin kaydı yok.
- SCHEMA_MIGRATION_CHECKSUM_MISMATCH: var olan beklenen sürümün checksum’u kaynak dosyayla eşleşmiyor. Eksik sürüm de varsa bu daha kritik uyuşmazlık önceliklidir.
- Yetki/bağlantı/SQLSTATE hataları mevcut ayrı PostgreSQL kodlarını korur.

Metadata’daki bilinmeyen sürüm adları/checksum içerikleri loglanmaz. Bilinen migration dosyaları değiştirilmez.
