# TOP 10 tekillik, kalite ve 60 aday seçimi

10.10.2026; başlangıç `4949b0d`, dal `feature/bist-development`.
GitHub dalındaki `03e6c82` commit'i geliştirme dalına birleştirildi;
aynı eskilik düzeltmesi ve ek testleri korundu. Main birleştirmesi yapılmadı.

## Davranış

- `top10_aday_secimi.prepare_candidates`: BIST ön ekini ve `.IS`/`.E`
  son eklerini normalize eder. Aynı sembolde önce geçerli, sonra en yeni gözlem
  seçilir; gözlem zamanı da eşitse normalize edilmiş içerik sabit karar verir.
- Fiyat pozitif ve sonlu olmalı. Sunulmuş sayısal teknik girdiler eksik,
  NaN/Infinity, boolean veya bozuk metin olamaz. RSI 0–100, SMA pozitif,
  hacim oranları/ATR negatif olmayan değerler olmalı. Sunulmuş zamanlar geçerli,
  geçmişte ve mevcut `stale_at` kurallarına göre güncel olmalı. Teknik dokümanda
  mod, veri zamanı, eskilik, fiyat/kapanış uyumu ve sunulmuş OHLC/hacim kontrolü var.
- Eski, zaman metadata'sı bulunmayan kayıtlar korunur; metadata'nın yokluğu
  güncellik kanıtı olarak sunulmaz. Mevcut algoritmanın ham uygunluk kapıları
  çalışmaya devam eder. Bu değişiklik eski kayıtlar için yeni veri icat etmez.
- Yarın sıralaması: mevcut final baz puanı, hacim oranı ve risk/getiri sırası
  korunur; tam eşitlikte sembol artan sırası eklenir. En fazla 60 uygun baz
  aday seçilir, mevcut öğrenme katkısı bu adaylara uygulanır, ilk 10 döndürülür.
  60'tan az uygun aday varsa liste doldurulmaz. 61. aday öğrenme bonusuyla
  havuza giremez; 60. aday ilk 10'a yükselebilir.
- Pozitif kapanış yolu mevcut opportunity puanını ve sembol eşitlik ölçütünü
  kullanarak 60 aday seçer. Tüm pozitif havuz, TOP30/50 performans verileri ve
  elenen pozitif aday sayısı/kalite tanıları korunur. Tümü kalitesiz pozitif
  veriyle boş snapshot yazılmasını engelleyen mevcut kontrol korunur.
- Gün içi sıralaması: mevcut gün içi modelin final puanı, hacim3 oranı ve
  momentum15 sırası korunur; tam eşitlikte sembol sırası eklenir. Ham ≥45
  kapısından geçen en fazla 60 adaydan ilk 10 seçilir. 60 sınırı tüm evrenin
  taranmasını veya Hisse Ara kayıtlarının sayısını sınırlandırmaz.
- Snapshot/web raporuna eklenen `aday_secimi`, limit/sayı/baz yöntem/sembolleri
  kaydeder. Mevcut `top10` alanı ve okuyucuları korunur. Ham ve shadow kontrol
  listeleri temizlenmiş, baz sırası verilmiş adaylardan deterministik seçilir.

Puan formülleri, ağırlıklar, öğrenme katkısı sınırları ve mevcut uygunluk
eşikleri değişmedi. Değişiklik daha yüksek tahmin doğruluğu iddiası değildir.
Yeni veri kaynağı isteği, ücretli servis veya kalıcı veri şeması eklenmedi.

## Yalnız yeni değişikliğin testleri

```sh
BIST_DATA_DIR=/workspace/scratch/bist-test-runtime /workspace/bist-venv/bin/python -m unittest discover -s tests -p 'test_top10_candidate_selection.py'
```

Sonuç: **33 yeni test geçti**. Kapsam: sembol alias/tekrarları, girdi sırasından
bağımsız eşitlik, en yeni geçerli gözlem, NaN/Infinity/eksik girdiler,
eski/gelecek/bozuk metadata, OHLC/hacim uyumu, legacy davranışı, gerçek intraday
indikatör şeması, mevcut eşitlik ölçütleri ve uygunluk eşikleri, kalibrasyon
NaN'ının puan tavanıyla geçerli hale gelmemesi, 60/61 sınırı ve öğrenme,
tekrarlanan taramada adayın havuzdan çıkması, pozitif havuz tanıları, gerçek
gün içi tarama callback'i ve izole snapshot/arşiv entegrasyonu.

Syntax kontrolü değişen/yeni Python dosyalarında; import kontrolü
`top10_aday_secimi`, `bist_bot`, `pozitif_kapanis` için geçti.
Önceki 1.369 Python/18 JavaScript regresyon kontrolü tekrar çalıştırılmadı.
Yerel log: `/workspace/scratch/bist-results/candidate-selection.log`.
Testlerde veri ve sağlayıcı mock'ları/geçici dizinler kullanıldı.

PostgreSQL, migrations, `v6_storage`, `STORAGE_BACKEND`, Railway ayarları ve
deponun veri dosyaları değiştirilmedi. Deployment komutu çalıştırılmadı.
