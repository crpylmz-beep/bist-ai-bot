# Pozitif kapanış havuzu — adım 20

Mevcut seans sonrası worker, erişilebilir BIST evrenini küçük batch'lerle tarar. Günlük kapanış / önceki kapanış değişimi **> 0** olan tüm hisseler incelenir; sayı sınırı ve minimum yükseliş yüzdesi yoktur. Kaliteli ama öneriye uygun olmayan pozitif hisseler de dondurulmuş gözlem havuzunda saklanır. Veri kalitesinden elenenler filtre gerekçeleriyle kaydedilir. Provider erişimi olmayan hisseler için veri uydurulmaz; mevcut en az %80 tarama kapsamı şartı korunur ve `total_checked/total_universe` raporlanır.

## Zaman, veri ve güvenlik

Europe/Istanbul kullanılır. Çalışma hafta içi 18:15 sonrasında, feature cutoff aynı gün 18:10 olacak şekilde yapılır. Kapalı günlük barlardan sonra hesaplanan göstergelerde gerçek `calculated_at` korunur; feature cutoff ile gerçek snapshot `captured_at` ayrıdır. Aynı tarihteki tamamlanmış arşiv yeniden hesaplanmaz. Kesintide tamamlanan batch'ler private runtime checkpoint'ten devam eder; ertesi gün veya evren değişince eski checkpoint kullanılmaz.

Günlük RSI/MACD/SMA/ATR/OBV/Bollinger/momentum mevcut analizden alınır. Kısa günlük EMA ve kapanış/hacim özeti ortak teknik hesaplama sırasında bir kez üretilir; MACD histogram iyileşmesi mevcut hesaplamadan aktarılır. Gerçek seans VWAP ancak mevcut Gün İçi analizinde T kapanışına kadar bilinen, aynı gün, en fazla 20 dakika eski veri varsa tekrar kullanılır. `source_asof`, `source_data_time`, `observation_scope` saklanır; bu son bilinen VWAP'tır, kapanış sonrası yeniden üretilmiş final VWAP iddiası değildir. Günlük hacim referansı seans VWAP diye sunulmaz. Gün İçi dosyasına yazılmaz.

Piyasa, haber/KAP/şirket, makro kaynakları yalnız kapanışa kadar gözlenmiş cache kayıtlarından alınır. Zamanı doğrulanamayan bağlam bilinmiyor kalır; gelecekte gözlenmiş haber ve sonuç geçmişi kullanılmaz. Doğrulanamayan kritik negatif haber/makro puanı öneri engeli oluşturur. Sonradan oluşan outcome hiçbir zaman T snapshot'ına geri yazılmaz.

Stale/eksik teknik veri, kapanış fiyatı uyumsuzluğu ve düşük/bilinmeyen TL likiditesi kalite havuzundan elenir. Mevcut nihai AI, sert düşüş, aşırı yükseliş, negatif kritik haber, stop/hedef ve risk/getiri kuralları öneri için korunur. Fırsat puanı bu engelleri aşamaz. Güven <40, fırsat puanı <50, mevcut uygunluk puanı <55, risk/getiri <1.5, >=%7 yükseliş veya geçerli `stop < fiyat < hedef` bulunmaması TOP listesine engeldir. Engellenen kaliteli pozitif hisse gözlem havuzunda kalır.

## Tahmin ve sıralama

`POSITIVE_OPPORTUNITY_V1` dondurulmuş girdilerden erken hareket, sürdürülebilirlik, uzamış hareket cezası, continuation olasılığı ve 1/3/5 günlük beklenti üretir. Bugünkü yüzde getiri doğrudan sıralama anahtarı değildir; uzama/güvenlik girdisidir.

Yeterli geçmiş olduğunda, yalnız cutoff'tan önce tamamlanıp gözlenmiş aynı rejimdeki benzer sinyaller kullanılır. En az 5 bilinen karar dışı kriter, bunlarda >=%70 benzerlik, bilinen MAE, **50 örnek / 7 ayrı gün** gerekir. Beklenti = gerçek medyan getiri − 0.15 × medyan mutlak MAE. Devam olasılığı, başarılı devam sayısının Beta(1,1) yumuşatılmış oranıdır. Her ufkun beklentisi ayrı kendi sonuçlarından hesaplanır.

Yeterli örnek yokken ATR, risk/getiri ve devam işaretlerinden **kalibre edilmemiş teknik senaryo** üretilir; ekranda ve `expected_return_method` alanında açıkça belirtilir. Bu başlangıç senaryosu istatistiksel tahmin veya doğrulanmış olasılık değildir. Güven en fazla 60; ampirik beklentide de mevcut nihai AI güvenini aşamaz. Sıfır olmayan tarihçe performansı varmış gibi gösterilmez.

Fırsat puanı bileşenleri: beklenti %15, devam %15, erken hareket %10, sürdürülebilirlik %10, teknik %14, hacim %8, sektör %3, piyasa %3, haber %3, makro %2, breadth %2, risk/getiri %8, güven %7. Sonuçtan uzama cezasının 0.4 katı ve yüksek riskte 10 puan düşülür; sonuç 0–100 aralığına alınır. Bileşenler/ağırlıklar sürümlü snapshot'ta tutulur; otomatik değiştirilmez.

Tüm kalite havuzu `rank` ile, öneri engellerini geçenler ayrıca `selection_rank` ile sıralanır. İlk 10 Yarın TOP10, 11–20 ve 21–30 diğer güçlü adaylardır; isteğe bağlı 31–50 gösterilir. TOP50 arşiv sınırı değildir: tüm kaliteli pozitif adaylar saklanır. `neden_bu_sirada`, `neden_daha_asagida`, gerekçeler ve riskler kayıtlıdır. Mevcut canlı/dondurulmuş/performance ayrımı korunur. Canlı kaynakta bulunmayan ek aday fiyatı açıkça kapanış/son seans diye etiketlenir.

## Sonuç, öğrenme ve shadow

Mevcut performans motoru `POSITIVE_CANDIDATE` modelini 1/3/5 günlük ufuklarla takip eder; OHLC, kapanış getirisi, MFE/MAE ve hedef/stop mevcut sağlayıcı ve sınırlı sembol cache'iyle değerlendirilir. Bu kayıtlar `analysis_only` olup eski ana AI geçmiş katkısına ve ana model başarı sayacına dahil edilmez.

Kapanış getirisi >%0.1 CONTINUED, <%−0.1 FAILED_CONTINUATION, arası NEUTRAL. Pozitif kapanış ayrıca >0 olarak ölçülür. Bunlar trade hedef/stop sonucundan ayrı etiketlerdir; aynı barda hedef/stop sırası belirsizliği yönü bilinen kapanış sonucunu yok etmez. Eksik OHLC / eksik işlem günü ölçüme alınmaz. Bütün günlük kalite havuzunun outcome'u tamamlanmadan o gün toplu capture/calibration hesaplarına katılmaz; küçük batch kaynaklı seçim yanlılığı önlenir.

TOP10/30/50 winner recall/capture paydası **dünkü dondurulmuş kaliteli pozitif havuzun güçlü kazananlarıdır**, tüm BIST değildir. Güçlü kazanan varsayılan >=%2 kapanış getirisidir. Precision = seçilen güçlü kazanan / seçilen; false positive rate = seçilen kazanmayan / tüm havuzdaki kazanmayan. Her iki ölçü birlikte raporlanır. Küçük örnekte yüzdeler `null`, sayılar görünür. Genel raporlar en az **40 örnek / 5 gün** ister; recall için kazanan örnek sayısı da bu şartı sağlamalıdır. Günlük tek seans için oran yerine sayılar ve yetersiz örnek durumu korunur.

1–5/6–10/11–20/21–30/31–50 sıra bucket'ları; beklenen getiri ve olasılık kalibrasyonu; risk, rejim ve sektör profilleri ayrıdır. Risk karşılaştırması MAE, yüksek/düşük aralığı ve stop oranıdır; portföy maksimum drawdown'u diye sunulmaz. 5/20/60 gün kriterli kontrol grubu karşılaştırması ve 19. adım kombinasyon motoru tekrar kullanılır; kombinasyonlar en az 50 örnek / 7 gün ister. Az örnekte özel rejim/sektör kuralı ve kesin örüntü ilan edilmez.

Aynı uygun havuz üzerinde eski kalibrasyon/piyasa modelinin puanı `baseline_rank`, yeni fırsat sırası `selection_rank`, mevcut kontrollü shadow düzeltmesi `shadow_rank` olarak freeze edilir. Sonradan oluşan rank tahmini yerine bu donmuş üyelikler karşılaştırılır. `MISSED_WINNER`, gözlenmiş rank/filtre/ceza/confidence gerekçesiyle mevcut private hata günlüğüne eklenir; nedensel hata veya doğru ağırlık bulunduğu iddia edilmez.

`LEARNING_ENABLED=false`, raporlarda `learning_enabled=false`, `automatic_application=false`. Kriterler ölçülür, kontrol grupları ve shadow karşılaştırılır; ana model ağırlıkları otomatik değişmez.

## Kalıcı kayıtlar ve cloud

`BIST_DATA_DIR` mevcut merkezi yol mimarisiyle kullanılır:

- Immutable: `/data/public/yarin_top10_arsiv/YYYY-MM-DD.json` içinde `pozitif_havuz.adaylar`; eski arşivler aynen okunur.
- Public pointer: `/data/public/yarin_top10.json`; mevcut Yarın canlı dosyası ayrıdır.
- Public ölçüm: `/data/public/pozitif_hisseler_performansi.json`; UI AI Öğrenme / Model Performansı bölümünde okur.
- Private restart checkpoint: `/data/runtime/pozitif_kapanis_tarama.json`.
- Private performans kayıtları ve MISSED_WINNER: mevcut runtime performans deposu ve `/data/runtime/karar_hata_gunlugu.json`.

Environment yoksa mevcut yerel yollar korunur. JSON yazımları mevcut lock/atomic mekanizmasını kullanır. `cloud_baslat.py`, web sunucusu, iki process mimarisi, volume, /health, push ve VAPID değişmez. Yeni kapanış analizi mevcut worker callback'ine, outcome takibi mevcut performans görevine bağlanmıştır; yeni scheduler/process kurulmaz.

Opsiyonel ayarlar: `POSITIVE_MIN_TURNOVER_TL=1000000`, `POSITIVE_WINNER_RETURN_PCT=2`. Yeni dependency veya secret gerekmez. Gerçek ortalama pozitif sayısı veri biriktikçe `average_analyzed_positive_count` alanında ölçülür; fixture sayıları gerçek piyasa ortalaması değildir.

## Doğrulama

`python -m unittest discover -s tests` ve `node tests/test_pozitif_kapanis_ui.cjs`. Yeni testler küçük pozitif/280 aday, doğrudan getiri yerine fırsat sırası, hard-safety, provider/cache/batch, cutoff ve gelecekteki fiyat/haber/model/outcome, immutable snapshot, 1/3/5 sonuçlar, tüm kalibrasyonlar/kontrol grupları, capture/recall/precision/FPR, private hata kayıtları ve HTTP/UI davranışını kapsar. Mobil browser smoke 430×932 Chromium emülasyonudur; fiziksel iPhone veya canlı Railway seansı değildir.

## Vade genişletmesi: 1 / 2 / 3 / 5 / 10 işlem günü

Pozitif adaylar artık `sonuc_1g`, `sonuc_2g`, `sonuc_3g`, `sonuc_5g`, `sonuc_10g` ile takip edilir. Yarın TOP10 kayıtlarına 2G eklenmiştir; daha önce var olan 20/60 günlük Yarın takipleri korunur. Haber/makro ve Gün İçi dakika vadeleri değiştirilmez. Eski kayıtlar tekrar arşivlenmeden, eksik 2G/10G sonuçları mevcut performans turunda tamamlanır. Tamamlanmış sonuçlar ikinci turda değiştirilmez.

İşlem günü sayımı `exchange-calendars==4.13.2` paketinin **XIST/Borsa İstanbul** takvimini kullanır. Hafta sonları, ulusal ve dini tam gün tatilleri atlanır; yarım seans işlem günü sayılır. Provider'da eksik bar olması tatil kabul edilmez. Mevcut özel tatil callback'i test/istisna için kullanılabilir. Sonuçlar kapanış tamamlanmadan üretilmez; yarım seanslar da mevcut muhafazakâr 18:15 kapanış kontrolünden sonra değerlendirilir. Takvim hatasında hafta içini otomatik işlem günü sayan fallback yoktur.

Her sonuç yalnız kendi son işlem gününe kadar normalleştirilmiş OHLC penceresini kullanır. Kapanış getirisi, dönem içi maksimum yükseliş/düşüş, en yüksek/en düşük fiyat, MFE/MAE, hedef/stop teması ve bilinen ilk temas sırası ayrı tutulur. Aynı bar içindeki bilinmeyen sıra `BELIRSIZ` kalır. `pozitif_sonuc` yön getirisinin >0 olmasını gösterir; trade `durum` ve kapanış devam sınıfı ayrı kavramlardır.

Public pozitif performans raporu beş vade için ayrı başarı, ortalama/medyan getiri, hedef/stop oranı, MFE/MAE ortalama/medyanı ve TOP10/30/50 ölçümleri içerir. Yeni 2G/10G outcome'lar **eski tahmin fiyatı, rank, expected return, olasılık, confidence, risk, fırsat puanı ve model sürümünü değiştirmez**. Geçmiş snapshot'ta 2G/10G expected return tahmini yoksa kalibrasyon için sonradan tahmin uydurulmaz; o bucket boş kalır.

`best_horizons` kriter/kombinasyon başına en iyi gözlenen vadeyi ölçer. Kıyaslamada yalnız tüm beş vadeyi tamamlamış **aynı günlük aday kohortları** kullanılır; 1G genç havuz ile 10G eski havuz karşılaştırılmaz. Her vade için en az 50 örnek / 7 ayrı gün gerekir. Yetersiz örnekte `best_horizon=null`; yeterli örnekte başarı oranı ve medyanla gözlenen en iyi vade seçilir. Wilson aralıkları ayrışmıyorsa `conclusive=false` ve UI'da “gözlenen; fark teyitli değil” yazılır. Bu gözlem otomatik öğrenme/ağırlık değişikliği değildir.

AI Öğrenme / Model Performansı ekranında 1G/2G/3G/5G/10G kompakt satırları ve kombinasyon vade özeti görünür. Yeni doğrulamalar `tests/test_pozitif_vadeler.py` içinde; gerçek push veya piyasa fiyatı kullanılmaz. Bağımlılık kurulumu mevcut `requirements.txt` üzerinden yapılır. Railway mimarisi, volume, worker başlatıcısı, push ve snapshot yazım yapısı değişmez.
