# Onay bekleyen en küçük canlı teşhis planı

**Uygulanmadı.** Railway log/SSH erişimi bu ortamda mevcut değildir.
Production sürüm kimliği, geçmiş `error_code` ve /health doğrulanamamıştır.
GitHub main kaynağı incelenebilir; main SHA'sı çalışan deployment kanıtı değildir.

## Önce mevcut kanıt

Railway read-only deployment/log erişimi sağlanınca aktif commit SHA'sını ve
`[V6_SCHEMA_ONCE_RESULT]` satırındaki mevcut alanları kontrol et. Eski logda
`error_code` yoksa bir değer varsayma. Mevcut main başlatıcısı özel kodları
loglayabilecek biçimde yazılmıştır; gerçek deployment ayrıca doğrulanmalıdır.

## Tercih: uygulama deploy/restart yapmadan izole teşhis kodu

Onaydan sonra, Railway SSH gerçekten erişilebiliyorsa:

1. Uygulama/container koduna dokunmadan, /tmp altında küçük bir izole Python
   paket kopyası hazırla. Yalnız mevcut v6_storage kaynak modülleri ve migration
   SQL dosyaları kullanılır; /data'dan hiçbir dosya kopyalanmaz. Symlink izlenmez.
2. Bu diagnostic commit'teki üç Python dosyasını kullan:
   `v6_storage/__main__.py`, `v6_storage/postgres.py`,
   `v6_storage/schema_diagnostics.py`. Kaynak GitHub commit SHA'sıyla sabitlenir;
   dosya checksum'ları doğrulanır. 631 pay evreni ve diğer ancestor commit'ler
   uygulama sürümüne taşınmaz.
3. Çalışma dizini izole /tmp klasörü olsun; yalnız eksik uygulama modülleri için
   `/app` Python path'e eklenir. Mevcut bağlantı değişkenleri süreç içinde
   kullanılır, yazdırılmaz. `PYTHONDONTWRITEBYTECODE=1`, `python -B` kullanılır.
4. **Yalnız** `python -B -m v6_storage schema --check` çalıştırılır. `schema`
   tek başına, `migrate`, startup schema flag veya STORAGE_BACKEND değişikliği
   yapılmaz. Salt okunur işlem koruması mevcut şemayı/checksum'ları sorgular.
5. Yalnız sabit güvenli JSON hata/success alanları raporlanır. Başarısızlıkta
   durulur; timeout sonrası otomatik schema apply veya migration denenmez.

Bu seçenek yeni Railway kaynağı oluşturmaz, main merge veya uygulama deploy
etmez, worker'ı restart etmez, PostgreSQL'e DDL/DML göndermez ve /data yazmaz.
İzole kodun canlıda tek sefer yürütülmesi için kullanıcı onayı gereklidir.

## SSH seçeneği yoksa

Dur. Otomatik olarak uygulama deployment'ına geçme. Aktif production commit'i
üzerine yalnız diagnostic commit farkını taşıyan ayrı bir release önerisi
hazırlanıp yeniden onaya sunulmalı; branch'in tüm ancestry'si deploy edilmemeli.
Önce mevcut schema-once flag ve startup recovery/write işlemleri incelenmeli:
`schema` komutunu kendiliğinden çalıştıran bir deployment, bu salt okunur teşhis
planının kapsamı değildir. /data'nın hiç değişmemesi şartı güvence altına
alınamıyorsa restart/deploy uygulanmamalı.

Şema başarılı şekilde gerçek sunucuda doğrulanmadan veri taşıma veya
STORAGE_BACKEND değişikliği için yetki verilmiş sayılmaz.
