# Ortak KAP şirket payı evreni

`pay_evreni.symbols()` tüm otomatik hisse taramalarının ortak kaynağıdır.
KAP Pazarlar kaynağının PAY PİYASASI 1/2/3/4/16 pazarları kabul edilir.
Doğrulanmış başlangıç listesi 631 paydır; 173 pay dışı ihraççı kodu ve
KTEST bu pazarlarda bulunmadığı için taranmaz. DMLKT şirket payı değildir.
KRDMA/KRDMB/KRDMD ve ISATR/ISBTR/ISCTR/ISKUR ayrı paylar olarak korunur.
Yıldız 149, Ana 394, Alt 49, Yakın İzleme 20, PÖİP 19.
Kaynak: https://www.kap.org.tr/tr/Pazarlar (2026-10-09 doğrulaması).
Liste bir işlem sırası için o gün işlem yapılabilirlik garantisi değildir.

İlk çağrı doğrulanmış paket listesini döndürür. İstanbul takvim günü başına
tek arka plan yenilemesi yapılır; timeout ve 4 MiB yanıt sınırı vardır.
Beş pazarın tamamı, tekil kodlar, şirket türü ve fon ayrımı doğrulanır.
Büyük üyelik değişimi otomatik kabul edilmez ve inceleme gerektirir.
Hatalarda son doğrulanmış bellek listesi korunur ve KAP_UNIVERSE uyarısı
verilir; companies() / 805 veya başarısız XUTUM sonucu yedek kaynak değildir.
Yenileme hiçbir kalıcı dosya yazmaz; restart doğrulanmış paket listesinden
başlar ve kaynağı yeniden kontrol eder. Güncel liste diske otomatik taşınmaz.
Eski market_context evren önbelleğindeki XUTUM etiketi yeniden kullanılmaz.
Pazar kapsamı değişikliği algoritmanın puanlama formülünü değiştirmez.

Günlük OHLC aynı sembol/period için eşzamanlı isteklerde kilitle birleştirilir.
En fazla 650 bellek girdisi, bir saniye TTL ve bağımsız sonuç kopyaları kullanılır.
Hatalar önbelleğe alınmaz; ayrı 5 dakikalık veri katmanına müdahale edilmez.
Manuel hisse analizi evren üyeliği ile engellenmez. Eski tahminler silinmez.
KAP haberinden doğan öncelikli analiz de evren kontrolünden geçer.

## Karşılaştırma sınırları

Mevcut kod daha önce XUTUM'dan 582 pay seçiyordu; yeni kapsam 631'dir.
805, kullanıcının tespit ettiği eski companies() ihraççı evrenidir.
Aynı iki örtüşen tur ve altı thread için 2 ms mock sağlayıcı ölçümü:
805 kod: 1610 sorgu / 0.900 sn; 631 pay: 631 sorgu / 0.439 sn.
Sorgu azalması %60.8; salt evren küçülmesi %21.6'dır.
Bu sayılar gerçek piyasa süresi veya production performansı değildir.
631 eşzamanlı paya birer gerçek sorgu gerekir; sonuçsuz sağlayıcı cevapları
başarı sayılmaz. Gerçek tam tarama yapılmamış, production ayarı değişmemiştir.
