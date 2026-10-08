# Haber akışı

Worker artık `company_site` görevini kaydetmez. Eski şirket sitesi dosyaları ve öğrenme geçmişi korunur; manuel modül kullanımı kaldırılmaz.

KAP mevcut 60 saniyelik bağımsız akışıyla birincil kaynaktır. `economy_news` varsayılan 900 saniyede Ekonomim, Bloomberg HT, Ensonhaber Ekonomi sırasıyla halka açık RSS uçlarını kontrol eder. KAP aynı olaya eklendiğinde ana kaynak KAP olur; tek canonical kimlik tek analiz/etki üretir. Bağımsız görevler nedeniyle KAP isteğinin her haberden önce tamamlanması garanti edilmez.

RSS adresleri `EKONOMIM_RSS_URL`, `BLOOMBERG_HT_RSS_URL`, `ENSONHABER_EKONOMI_RSS_URL` ile aynı yayıncı HTTPS alanındaki doğrulanmış resmi adreslere ayarlanabilir. Varsayılan adreslerin bu geliştirme ortamında canlı doğrulaması yapılamadı: dış HTTPS istekleri ProxyError verdi. Bu uçların mevcut ve RSS olduğu iddia edilmez. Yayıncının kullanım şartları ve RSS kullanım izni kurulumda ayrıca doğrulanmalıdır; robots.txt izin kontrolü tek başına kullanım lisansı değildir.

Robots.txt alınamazsa veya erişim yasaksa kaynak işlenmez. Yönlendirme, giriş/paywall, HTML yanıt, DTD/entity ve 512.000 byte üzeri yanıt reddedilir. Makale sayfası indirilmez. Her kaynak tur başına en fazla 30 RSS öğesi, her öğe en fazla 10 açık BIST sembolü işler. Şirket adıyla belirsiz eşleştirme yapılmaz. Gelecek tarihli, tarihsiz, 2 günden eski ve hisse sembolü içermeyen içerik kaydedilmez. Saklanan yeni metin en fazla 1.200 karakter RSS özeti ve 500 karakter başlıktır; ham feed/HTML/yanıt arşivi oluşturulmaz.

Kaynak hataları diğer kaynakları durdurmaz; tur sonunda TaskIssue ile worker'ın gerçek hata/backoff mekanizmasına iletilir. Tamamlanmış tekrar haber canonical dosyayı yeniden yazmaz. Benzersiz analiz/öğrenme kayıtları otomatik silinmez. Mevcut skor formülleri aynen kullanılır; haber etkisi kural tabanlı tahmindir, doğrulanmış nedensellik değildir.

Her turda üç kaynak ayrı `[NEWS_HEALTH]` satırı üretir: durum, sabit hata kodu, işlenen/atlanmış adetler. Son tur `runtime/economy_news_health.json` içinde sabit üç kayıt olarak atomik saklanır; append/geçmiş oluşturulmaz. `/health` çıktısındaki `news_sources` yalnız bu üç kaynağın güvenli alanlarını gösterir. `OK` geçerli RSS'nin okunabildiğini ifade eder; işlenen hisse haberi sayısı sıfır olabilir. Evren alınamazsa kaynaklar `BLOCKED/EMPTY_UNIVERSE` olur; erişilmiş gibi raporlanmaz.
