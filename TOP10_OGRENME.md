# Yarın TOP10 kontrollü öğrenme

Mevcut `yarin_kalibrasyon.py` katmanı, `sinyal_performansi.json` içindeki
doğrulanmış indikatör sonuçlarını batch başına bir kez okur. Yeni bir eğitim
motoru veya geçmiş dosyası oluşturulmaz. Normal teknik sıralama ve üretimdeki
pozitif kapanış havuzu aynı katmanı kullanır; mevcut uygunluk filtreleri korunur.

`base_score` eski sıralama skorudur. Pozitif kapanış yolunda bu değer mevcut
future opportunity score'dur. Öğrenme düzeltmesi ayrı tutulur; teknik skor,
expected return, olasılık ve seviyeler yeniden hesaplanmaz.

Merkezi ayarlar `yarin_kalibrasyon.py` içindedir:

- Toplam düzeltme: en fazla ±3 puan; final sıralama skoru 0–100.
- Aile katkısı: en fazla ±0,75; aynı ailedeki katkılar toplanmaz, ortalanır.
- Kombinasyon katkısı: en fazla ±1; altı mevcut kombinasyondan en güçlü tek
  uygun kombinasyon seçilir ve bileşen ailelerinin katkısının yerine geçer.
  Güveni bileşenlerden düşük kombinasyon onların yerine kullanılamaz.
- Ortak güven eşikleri: <30 sıfır; 30–99 ×0,25; 100–299 ×0,60; 300+ ×1.
- Vade ağırlıkları: D+1 %80, D+3 %15, D+5 %5. D+1 uygun veri zorunludur.
  D+10/20/60 takipte kalır fakat bu düzeltmeye girmez.
- YARIN_TOP10 koşul verisi önceliklidir. Genel koşul verisine fallback ×0,5
  ek güven azaltımı uygular; baseline da aynı kaynak ve vadeden seçilir.

Edge, koşul ile aynı kohortun baseline'ı arasındaki başarı oranı, ortalama ve
medyan getiri farklarından oluşur. Normalize edilmiş her fark ±1 ile sınırlıdır;
ağırlıkları %40/%30/%30'dur. Güven, vade ve fallback katsayıları sonradan
uygulanır. Doğrulanmış MFE/MAE medyanları, varsa, pozitif katkıyı risk nedeniyle
azaltabilir; eski cache için ortalamalara dönüş vardır. Tek büyük getiri sınırsız
bonus oluşturamaz. Negatif edge aynı güven kapılarıyla sınırlı ceza üretir.

Cache bozuk, uyumsuz, geleceğe ait veya yedi günden eskiyse etki sıfırdır.
Eksik fiyat/feature, yetersiz veya doğrulanmamış istatistik, geleceğe ait feature
ve hesaplama hatası da eski sıralamaya güvenli dönüş sağlar. Pending ve
doğrulanmamış sonuçlar mevcut ortak veri kalite filtresiyle öğrenmeye alınmaz.
Cache zamanı tahmin zamanından sonra olamaz.

## Kapatma

`TOP10_LEARNING_ENABLED=false` yeni tahminlerde eski sıralamayı birebir kullanır.
Varsayılan açıktır. Railway Variables üzerinden değiştirilir; kod değişikliği
gerekmez. Daha önce kilitlenmiş günlük snapshot tekrar yazılmaz; anahtar
değişikliği geçmiş tahmini geriye dönük değiştirmez.

## Donmuş karşılaştırma ve açıklama

Mevcut günlük snapshot içinde `base_top10`, gerçek öğrenilmiş `top10` ve
en fazla 20 sembollük `learning_comparison` saklanır. Her adayın temel/final
skoru, temel/öğrenilmiş sırası, sıra değişimi, sürümü, güven özeti ve
`learning_reasons` kaydedilir. Gerekçeler kullanılan koşul, vade, kaynak,
örnek sayısı, baseline, güven ve gerçek sınırlandırılmış katkıyı gösterir.

BASE kontrol grubu mevcut performans motorunda `YARIN_LEARNING_BASELINE`
olarak izlenir. Aynı snapshot kohortunun BASE/LEARNED sonuçları rapordaki
`top10_learning_comparison` alanında mevcut 1/3/5/10/20/60 işlem günü
pipeline'ıyla karşılaştırılır. BASE kontrol sonuçları öğrenme girdisi değildir.
Mevcut arşivler, kullanıcı verileri ve geçmiş sonuçlar yeniden yazılmaz/silinmez.

Doğrulama: `tests/test_top10_learning.py`, tam Python regresyonu, tüm mevcut
JavaScript smoke grupları ve geçici veri köküyle worker `--check`.
