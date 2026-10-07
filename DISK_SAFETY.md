# Railway /data disk güvenliği

## Koddan doğrulanan başlangıç sorunu

Eski `copy_new`, hedef zaten mevcut olsa bile önce `.migration-*` içinde kaynağın tamamını kopyalıyordu; ancak `os.link` sırasında hedefin var olduğunu görüyordu. Bootstrap her web/worker açılışında çağrılıyor. Repo BIST public seed'i yaklaşık 6.3 MiB; 500 MB volume %99 doluyken yaklaşık 5 MB boş alanla bu gereksiz kopya ENOSPC üretir. Normal exception `finally` geçiciyi kaldırır; SIGKILL/yarım kalan container geçici bırakabilir. Bu durum crash'in koddan doğrulanmış nedenidir; kalıcı 500 MB kullanımın hangi dosyalardan oluştuğu production boyut raporu olmadan doğrulanamaz.

Yeni kopyalama mevcut hedefi temp oluşturmadan atlar. Hedef dizin lock'u altında tekrar kontrol edilir; iki process aynı kaynağı aynı hedef için iki kez kopyalayamaz. Hard-link ile atomik create ve hedefi overwrite etmeme korunur. Kaynak boyutu + 1 MiB rezerv kadar boş alan gerekir. ENOSPC/EDQUOT kontrollü uyarı ve ertelenmiş kopya sonucudur; kaynak ve mevcut hedef korunur. Fsync başarısızsa yeni hedef hiç kurulmamış veya tam byte kopyası kurulmuş olabilir; eski hedef kesinlikle overwrite edilmez. Public bootstrap'ın optional pointer yazımı da alan tükenmesinde ertelenir.

## Envanter / büyüme

- `/data/public`: BIST/Gün İçi/Yarın canlı ve son durum JSON'ları, piyasa/haber/makro/şirket özetleri ve yeniden üretilebilir performans raporları. Dosyalar genellikle aynı adla atomic replace edilir. TOP10 snapshot pointer'ı arşivin public görünümüdür; arşivden ayrıdır.
- `/data/archives/yarin_top10_arsiv`: günlük immutable tahminler ve bütün kaliteli pozitif havuz. Gün sayısıyla büyür; **silinmez**.
- `/data/runtime/ai_ogrenme_gecmisi.json`, tahmin/haber/makro geçmişleri, `yarin_top10_sonuclar.json`, Gün İçi sinyal/outcome state'i, model sürümleri/controlled evidence ve `karar_hata_gunlugu.json`: gerçek kalıcı takip/öğrenme verisi. Model sürümleri training-id listeleri de büyür. **Silinmez, retention uygulanmaz.** 1/2/3/5/10/20/60 günlük takipler korunur.
- `/data/runtime/gun_ici_mumlar.json`: Gün İçi outcome için gereken fiyat kanıtı. Mevcut motorun kendi 7 günlük mantığı dışında bu düzeltmede değişmez; generic cache temizliğine dahil değildir.
- `/data/runtime/performans_fiyat_cache.json`: mevcut provider'dan tekrar okunabilen günlük OHLC replay cache'i. Önceden semboller ve eski günler temizlenmiyordu. Yeni kayıt en fazla son 3 gün ve konservatif yaklaşık 4 MiB JSON bütçesiyle sınırlıdır. Cache'den elenmek outcome/snapshot/forecast silmek değildir; gerektiğinde provider yeniden okunur.
- `/data/runtime/pozitif_kapanis_tarama.json`: yarım kalan kapanış taramasının günlük restart checkpoint'i; tek isimle replace edilir, korunur.
- `/data/private/user-data`: manuel seviyeler, fiyat alarmları, subscriptions ve notification outbox kullanıcı bazlı kalıcı verisi. **Hiçbir dosyası silinmez.**
- KAP/makro/news/şirket dedup state'i ve baseline dosyaları korunur; public haber görünümü mevcut 500 kart sınırını kullanır.
- Runtime log çıktıları stdout/stderr'a gider; uygulamada yeni sınırsız dosya log mekanizması yoktur. Repo içindeki `_backup_` Python/HTML/JSON ve `.bak` dosyaları eski patch araçlarının statik çıktılarıdır; cloud başlatıcısı bu patch scriptlerini çalıştırmaz. Offline opt-in `migrate` eski public dosyalarını kopyalayabilir, fakat yeni create kontrolü mevcut hedefi çoğaltmaz. Bu belirsiz backup'lar otomatik silinmez.

## Güvenli temizlik ve rapor

Child processler başlamadan önce volume genelinde dosya boyutları/grup toplamları ve dosya sistemi used/free/total loglanır. Private kullanıcı adları ve dosya içerikleri loglanmaz; bilinmeyen/özel dosyalar anonim kategoriyle görünür. Symlink hedefleri takip edilmez. Public top-level JSON ve bilinen runtime geçmiş/cache adları boyutlarıyla listelenebilir. Root altındaki beklenmedik dosyalar `other` grubuna dahil edilir.

Otomatik temizlik yalnız `/data/public/.migration-<known-public-seed-name>-*` altında 24 saatten eski, hedefi tanımlı public bootstrap scratch kopyalarını kaldırır. Yeni geçici adında hedef dosya adı bulunur. Eski hedefsiz `.migration-*` geçicileri neye ait oldukları doğrulanamadığından korunur. Fresh geçici, private/runtime/archive scratch, `.snapshot-*`, `.user-*`, `.bak` ve bilinmeyen dosyalar korunur. Bu diğer geçiciler son recoverable kalıcı kayıt olabilir; otomatik temizlenmez.

Boş alan <10 MiB ise, yalnız schema'sı doğrulanmış günlük provider replay cache'i lock altında kaldırılabilir. İçerik beklenen `day/closed/bars` cache modeli değilse silinmez. Gün İçi bar kanıtı veya herhangi bir geçmiş dosyası bu kurala dahil değildir.

Heartbeat atomic yazımında disk tükenirse worker sırf heartbeat yüzünden kapanmaz; eski dosya korunur ve açık hata loglanır. Bu durum sağlıklı persistence olarak sunulmaz: health mevcut timestamp'e göre stale olabilir. Alarm/outbox/history transaction hataları sessiz başarılı sayılmaz; kalıcı yazım semantiği değişmez.

## Kapasite sınırı

Bu düzeltme gereksiz startup kopyalarını, aged public scratch ve günlük replay cache büyümesini önler. **Gerçek kalıcı geçmiş sınırsız korunacaksa 500 MB üzerinde sonsuza kadar çalışma garantisi yoktur.** Rapor `archives/runtime/private` toplamlarının kapasiteyi tükettiğini gösterirse Railway volume kapasitesi artırılmalıdır; uygulama bunları yer açmak için silmez. Full disk'te hiçbir güvenli temizlenebilir dosya yoksa kalıcı işlem yapılabilmesi kapasite artışına bağlıdır.

Gerçek production volume'a bu geliştirme ortamından erişim yoktur; dosya bazında 500 MB dağılımı veya deploy sonrası health henüz doğrulanmış değildir. İlk yeni deployment Logs içindeki `[DISK]` raporu bu ayrımı görünür yapar.

## DISK_ONCE_V1 production teşhis / tek seferlik alan açma

Worker, kendi exclusive `ana_motor.lock` kilidini aldıktan sonra, collector'ları başlatmadan `reclaim_once(paths())` çağırır. Web process ayrı çalışmaya devam edebilir; private kullanıcı dizinine temizlik için girilmez. Başlangıç `[DISK]` raporuna insan tarafından okunabilen MiB dizin toplamları ve en büyük 30 dosya eklendi. İçerik/token/kullanıcı kimliği loglanmaz. Bu rapor production volume'un hangi korunmuş dosyalardan büyüdüğünü göstermek içindir; geliştirme volume boyutları production sonucu diye sunulmaz.

İşlem `/data/runtime/disk_reclaim_v1.json` işaretini **silmeden önce** STARTED olarak atomik yazar. İşaret yazılamazsa hiçbir dosya silmez. İşaret mevcutsa, STARTED/COMPLETED fark etmeksizin sonraki başlangıçta tekrar temizlik yapmaz. Tek seferlik mutex ve mevcut worker kilidi birden fazla worker/cleanup turunu engeller. Sonuç küçük aynı marker'da saklanır; yeni bir backup/hata geçmişi dizisi oluşmaz.

Güvenli adaylar:

- Schema'sı doğrulanmış günlük `performans_fiyat_cache.json` provider replay cache'i; tahmin/outcome değil. Büyük cache dosyaları tümü RAM'e alınmadan, sembol başına en fazla yaklaşık 4 MiB tamponla streaming olarak doğrulanır. Beklenen fiyat cache şeması, tarih ve closed bayrağı doğrulanamazsa dosya korunur.
- Public/runtime/archive içindeki 24 saatten eski `.migration-*`, `.user-*.tmp`, `.snapshot-*.tmp` dosyaları **yalnız aynı dizindeki korunmuş normal JSON dosyasıyla byte-identical ise**. SHA-256 stream ile hesaplanır, boyut/inode/mtime kopya ve kaynakta tekrar kontrol edilir. Eski hedefsiz temp de ancak bu exact-match kanıtıyla silinebilir; farklı/partial temp korunur.
- `dosya.json.bak` / `dosya.json.backup` sadece aynı dizindeki `dosya.json` ile boyut ve SHA-256 birebir eşleşirse kaldırılır. Unique eski backup, isimlendirmesi belirsiz backup, symlink ve son 24 saatteki adaylar korunur.

Asıl JSON, archive, tahmin geçmişi, tüm vadelerin performans/outcome kayıtları, model state'i, Gün İçi bar kanıtı ve private kullanıcı verisi silinmez. Yeniden üretilebilir olsa da `yarin_top10_sonuclar.json` takip raporunu silmek bu işlemde tercih edilmez. Kaynak dosyalar byte-identical temp/backup karşılaştırmasında sadece okunur; yeniden yazılmaz.

Hedef boş alan yaklaşık 150 MiB'dir; yeterli alan varsa veya hedefe ulaşılınca daha fazla aday silinmez. `[DISK_ONCE] BEFORE` ve `AFTER` satırları gerçek filesystem used/free/freed MiB ve temizlenen dosya kategorilerini gösterir. Freed değeri silinen dosya boyutlarını toplamaktan değil, gerçek free alan farkından gelir; hard-link/açık inode gibi nedenlerle unlink hemen alan açmayabilir. Marker'ın küçük yazımı ölçümden sonra yapılır.

150 MiB güvenli olarak açılamazsa explicit logla bildirilir; benzersiz kalıcı dosyalara genişletilmiş silme yapılmaz. Bu durumda volume kapasitesi artırılmalıdır. Normal 3 gün / ~4 MiB replay cache bütçesi ve eski startup disk koruması devam eder. Priority kodu/hata sınıflandırması bu adımda değiştirilmez; disk alanı açıldıktan sonraki loglarla ayrıca değerlendirilmelidir.

Production kazanımı, yeni deploy'un `[DISK_ONCE] AFTER ... freed_MiB=...` satırından doğrulanır. Bu satır görülmeden gerçek production temizlenen dosya/MB sonucu iddia edilemez.
