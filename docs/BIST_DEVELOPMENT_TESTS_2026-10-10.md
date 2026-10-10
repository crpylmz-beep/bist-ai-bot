# İlk TOP 10 geliştirmesi — test kaydı

Tarih: 10.10.2026. Dal: `feature/bist-development`.
Değişiklik: öğrenme katkısında hesap zamanı rapor eskilik kontrolü.
Ortam: Python 3.12.14, izole venv, requirements sürümleri, Node 24.19.0,
Playwright ve `/usr/bin/chromium`. Python 3.13 ayrıca denenmedi.

## Sonuçlar

| Kontrol | Sonuç |
| --- | --- |
| Önceki kodda yeni 3 test | 2 beklenen başarısızlık, 1 geçiş, 0 hata. Kaynak `git show HEAD:yarin_kalibrasyon.py` ile yalnız test sürecinde yüklendi; worktree geri alınmadı. |
| Düzeltmeden sonra TOP 10 öğrenme | 53 test geçti (3 yeni + 50 mevcut). |
| Geniş uygulama regresyonu | 35 test modülünde 1.369 test; ilk çalıştırmada 1.344 geçti, 24 hata ve 1 başarısızlık. Aşağıdaki ortam düzeltmeleriyle yalnız başarısız 25 test yeniden çalıştırıldı ve hepsi geçti. |
| JavaScript regresyonu | 18 test dosyasının tamamı geçti. İlk çalıştırmada 9 geçti; ortam kısıtına takılan 9 dosya yeniden çalıştırıldı ve geçti. |
| Syntax | Değişen iki Python dosyasına `ast.parse`: geçti. |
| Import | `yarin_kalibrasyon`, `bist_bot`, `performans_motoru`, `top10_ogrenme_performansi`, `gunluk_al_sat`, `web_server`, `ana_motor`: geçti. |
| Bağımlılıklar | İzole ortamda `python -m pip check`: bozuk bağımlılık yok. |
| Diff | `git diff --check`: geçti. Veri/storage/production dosyaları değişmedi. |

Yeni testler:

- `test_context_stale_guard_at_scoring_time`: yedi gün + bir saniyede sıfır
  katkı, `STALE_REPORT`, boş gerekçeler.
- `test_context_age_boundary_remains_usable`: tam yedi günlük bağlamın katkısı
  mevcut davranışla aynı.
- `test_reused_context_expiry_preserves_base_ranking`: yüklenmiş bağlam
  sonradan eskidiğinde baz puanları, sıralar ve rank_change korunur; cache
  yalnız bir kere okunur.

## Ortam hatalarının araştırılması

Başlangıçtaki 5 TOP 10 import hatası eksik `borsapy` nedeniyleydi; sabitlenmiş
requirements ayrı venv'e kurulduktan sonra geçti.

Geniş Python çalışmasındaki 23 HTTP test hatasının traceback'i yerel soket
oluşturulurken `PermissionError: Operation not permitted` gösterdi. Ağ izni
verilmiş sandbox komutunda bu testlerin 23'ü geçti. Browser testleri de Chromium
`setsockopt` engeline, Node VAPID testi `spawnSync EPERM` engeline takıldı;
aynı kapsamlı ortam izniyle yeniden çalıştırılan 9 JavaScript dosyası geçti.

Diğer iki Python testi (`test_worker_updates_context_and_survives_ai_error`,
`test_real_sigterm_shutdown`) kendi geçici `BIST_RUNTIME_DIR` yolunu seçiyordu;
dışarıdan uygulanan test `BIST_DATA_DIR` ile çelişiyordu. Modüller izole veri
köküyle import edildikten sonra sadece bu iki test için dış kök kaldırıldı;
yazımları kendi geçici worker dizinlerinde kaldı. Her ikisi de geçti. Ürün kodu
ve veri yolu doğrulaması bu ortam hataları için değiştirilmedi.

## Regresyon kapsamı

Python modülleri:

```text
test_top10_learning test_top10_comparison test_yarin_kalibrasyon
test_yarin_snapshot test_yarin_plani test_pozitif_kapanis test_pozitif_vadeler
test_performans_motoru test_tahmin_hafizasi test_sinyal_performansi
test_indicator_performance test_teknik_gostergeler test_teknik_performans
test_indicator_candidates test_piyasa_baglami test_market_regime
test_sector_strength test_kontrollu_ogrenme test_ai_karar_motoru
test_nihai_karar test_karar_teshis test_gunluk_al_sat test_gun_ici_performans
test_intraday_signal_performance test_fiyat_alarm_motoru
test_push_bildirim_motoru test_kullanici_kayitlari test_provider_boundaries
test_ana_motor test_gorev_hatalari test_ekonomi_haberleri
test_haber_tekillestirme test_sirket_site_motoru test_company_isolation
test_news_restrictions
```

JavaScript: mevcut `tests/*.cjs` dosyalarının 18'i. Mobil/masaüstü, yarın kartı,
model performansı, teknik göstergeler, alarm/push, piyasa rejimi, sektör ve
gün içi ekranları kapsandı.

PostgreSQL/storage/schema/disk yönetim testleri kapsam dışı. Gerçek migration,
production worker, canlı veri kaynağı taraması veya Web Push gönderimi yapılmadı.

TOP 10 testlerinin tekrar komutu (venv etkin ve veri kökü geçici olmalı):

```sh
BIST_DATA_DIR=/workspace/scratch/bist-test-runtime /workspace/bist-venv/bin/python -m unittest discover -s tests -p 'test_top10_learning.py'
```

Ham yerel loglar: `/workspace/scratch/bist-results/python-regression.log`,
`python-retry.log`, `javascript-regression.log`, `javascript-retry.log`,
`top10-before-fix.log`; yeşil TOP 10 logu `/workspace/scratch/bist-green.log`.
Loglar Git'e eklenmedi; bu dosya kalıcı sonuç kaydıdır.
