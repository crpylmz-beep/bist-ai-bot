# BASE / LEARNED gerçek sonuç karşılaştırması

Mevcut immutable snapshot'taki `base_top10` ve `top10`, mevcut performans
motorunda sırasıyla `YARIN_LEARNING_BASELINE` ve `YARIN_TOP10` olarak izlenir.
Yeni tahmin veya sağlayıcı katmanı yoktur. Sonuçlar mevcut XIST takvimi ve
1/3/5/10/20/60 işlem günü outcome pipeline'ından gelir. Eksik seans fiyatı
PENDING kalır; geçmiş snapshot yeniden sıralanmaz veya yazılmaz.

`top10_ogrenme_performansi.py` aynı snapshot kimliği ve aynı vadeyi eşleştirir.
Her iki listede de tam 10 benzersiz sembol, 1–10 sıra ve doğrulanmış sonuç
gereklidir. Daha kısa, eksik veya kirli listeler INSUFFICIENT olur. Legacy,
unverified, pending, geleceğe ait feature/sonuç, fiyat/getiri uyuşmazlığı ve
çakışan duplicate'lar tamamlanmış karşılaştırmaya alınmaz. Ortak sembollerin
donmuş referans ve sonuç fiyatları da tutarlı olmalıdır. BASE kontrollerinin
özel doğrulaması ortak kalite kapılarını tekrar kullanır; canlı öğrenme veri
kümesinin BASE/SHADOW yasağı değiştirilmez.

Her taraf için ortalama/medyan getiri, pozitif sayısı ve oranı, en iyi/en kötü
getiri, MFE/MAE ortalaması ve ekstremi, TOP3/TOP5/TOP10 getirileri saklanır.
Eksik MFE/MAE sıfır sayılmaz. Basit betimleyici risk oranı, ortalama getirinin
mutlak ortalama MAE'ye bölümüdür; MAE eksik veya sıfırsa oran yoktur.

Kazanan, eşleştirilmiş TOP10 **ortalama getiri farkıyla** belirlenir:
pozitif LEARNED_BETTER, negatif BASE_BETTER, mutlak fark <=1e-9 TIE.
Diğer metriklerin farkları da ayrıca görünür; karışık sonuçlar tek bir yatırım
skoruna çevrilmez. INSUFFICIENT sonuçlar kazanma oranının paydasına girmez.
Learned win rate = learned kazanılan gün / tamamlanmış gün; eşit günler
paydada kalır. Ortalama/medyan edge de yalnız tamamlanmış çiftlerden gelir.

7d/30d/90d/all_time kohortları donmuş tahmin zamanına göre seçilir; her vade
ayrı raporlanır. Sıra değişimleri ve TOP10'a giren/çıkan hisseler, her vadedeki
doğrulanmış getirileriyle görünür. Liste dışı sıralar snapshot'taki metadata'dan
gelir; bugünkü göstergelerle yeniden hesaplanmaz.

Cache: `BIST_DATA_DIR/public/top10_ogrenme_performansi.json`; yerel varsayılan
mevcut `webapp/data` yoludur. Mevcut lock + atomic replace kullanılır. Ham
tahmin geçmişi ve arşivler değiştirilmez/silinmez. Üretim performans raporunun
zamanlaması kullanılır; API geçmiş dosyalarını taramaz. Tüm zamanların
istatistikleri korunurken ayrıntı çıktısı son 100 karşılaştırma ve 2000 sıra
değişimi ile sınırlıdır. Bu sınırlar ham geçmişi silmez.

`GET /api/top10-learning-performance?horizon=1&period=all_time`

- horizon: 1,3,5,10,20,60; varsayılan 1.
- period: 7d,30d,90d,all_time; varsayılan all_time.
- Geçersiz/tekrarlanan/bilinmeyen filtre: 400.
- Eksik veya bozuk cache: 503.
- Çıktı: summary, horizons, periods, recent_comparisons, rank_changes.

Yardımcı rapor hata verirse güvenli log üretilir, önceki atomik cache korunur
ve ana performans raporu UNAVAILABLE durumunu gösterir; worker devam eder.
Cache `updated_at` zamanı eski rapor ile yeni veriyi ayırt etmeyi sağlar.
TOP10 formülü, ±3 sınırı, güven eşikleri, vade ağırlıkları, kill switch ve
diğer sinyal motorları değişmez. Bu rapor otomatik ağırlık güncellemez.
