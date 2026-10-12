# Hisse Detayı — Yarın İçin V1

Eski “Sonraki Seans” kartı genel analizden `yarin_*` alanlarını gösteriyordu. Kapanmış günlük mum referansı/plan güveni açık değildi. TOP10'un kullandığı eski `bist_bot` hesabı değiştirilmez. Hisse detayındaki tek kısa vadeli kart artık opsiyonel `tomorrow_plan` kullanır; orta/uzun vadeli kart ve otomatik/manüel seviyeler korunur.

## Veri ve kapanış

`yarin_plani.py`, yalnız seçilen sembol için çalışır. Önce beklenen son XIST seansının immutable planı, ardından 128 kayıt/5 dakika RAM cache okunur. Mevcut `performans_fiyat_cache.json` yeterli OHLCV içeriyorsa kullanılır. Bu cache'in eski OHLC sürümlerinde hacim yoktur; hacim uydurulmaz. Seçilen hisse için mevcut daily teknik kaynak bilgisi varsa aynı `bist_bot.bp.Ticker(...).history(period='6mo')` sağlayıcısına bir çağrı yapılabilir. Analizi/kaynak bilgisi olmayan sembollerde tarama başlatılmaz; yetersiz veri döner. Tüm BIST taranmaz, yeni fiyat veri katmanı oluşturulmaz.

Merkezi `closed_frame(...,'TOMORROW')`, XIST `business_day` ve `session_closed` kullanılır. Güvenli daily kapanış eşiği 18:15 İstanbul; `available_at` daha geçse o zaman korunur. Açık veya gelecekteki mumlar indikatörlerden önce çıkarılır. Son 51 seans OHLC geçerli ve kesintisiz olmalıdır. `as_of`, `reference_price`, sonraki XIST `plan_session`, engine version kayıtta bulunur.

## Seviye ve karar kuralları

- ATR14 gerçek true-range ortalamasıdır; sabit fiyat yüzdesi fallback yoktur. SMA20/SMA50, EMA21, RSI/MACD ve hacim oranı merkezi teknik yardımcılarla okunur.
- Destek/direnç: son kapanıştan önceki 5 tamamlanmış seansın low/high yapısı.
- Giriş ankrajı: `min(close, max(support, min(SMA20, EMA21)))`; alt sınır `max(support, anchor − 0.23 ATR)`, üst sınır `min(close, anchor + 0.03 ATR, resistance − 0.10 ATR)`.
- Stop `support − 0.25 ATR`; kâr al alt `min(resistance, close + 0.50 ATR)`, üst `min(resistance + 0.25 ATR, close + 0.80 ATR)`. Pozitif fiyat ve stop < giriş alt ≤ giriş üst < hedef sıralaması geçerli olmalıdır.
- R/R: giriş aralığı orta noktası; `(kâr al alt − giriş)/(giriş − stop)`. Bu giriş yöntemi yalnız plan ölçüsüdür, gerçekleşmiş işlem fiyatı değildir.
- Kırılım seviyesi gerçek önceki dirençtir. Fiyat üzerinde + pozitif mum + merkezi `VOLUME_CONFIRMATION` (130%) => CONFIRMED; fiyat üzerinde ama teyit eksik => WEAK_CONFIRMATION; aksi WAITING. Olası hedef `direnç + 0.60 ATR`, ancak son fiyatın üzerinde kaldığında; kesin hedef değildir.
- 8 gerçek kriter: fiyat>SMA20, SMA20>SMA50, RSI45–70, pozitif/güçlenen MACD, hacim teyidi, geçerli destek/giriş yapısı, merkezi min R/R1.2, pozitif kapanış mumu. Teyit bunların toplamıdır; ham güven `100 × teyit/8`.
- Hacim eksik: güven×0.75. Dirence0.25ATR yakınlık−15; düşükR/R−15; RSI≥70−10; EMA21'den merkezi3ATR uzama−25.
- Güçlü negatif trend, ≥%7 düşüş, aşırı uzama, eski seans veya geçersiz seviyeler: BEKLE, giriş/hedef/stop null, güven en fazla35. Bunlar TOP10 puanını etkilemez.
- UYGUN: blok yok, ≥6/8, güven≥70, yeterliR/R ve hacim bilgisi. Diğer geçerli planlar TEMKINLI. Yetersiz OHLC/ATR/geçmiş YETERSIZ_VERI.
- Reasons yalnız geçen kriterlerden; warnings yalnız gerçek risk koşullarından üretilir. RSI/MACD tek başına AL üretmez.

## Kalıcılık ve API

Yeni küçük kayıtlar: `/data/runtime/yarin_plan_arsivi/SEMBOL/YYYY-MM-DD.json` (yerelde `.local/runtime/...`). Kaynak tarih bazlı lock + atomic write + yalnız yoksa oluşturma; sonraki provider düzeltmeleri/AI hesapları eski planı değiştirmez. OHLCV kopyaları tutulmaz, mevcut geçmişe yazılmaz/silinmez. Yetersiz veri kaydı kalıcılaştırılmaz.

`GET /api/stocks/{symbol}` geriye uyumlu `tomorrow_plan` ekler. Snapshot'taki fiyatlar/güven/nedenler sabittir; `is_current_reference` ve `view_status` yalnız read-time sunum metadata'sıdır. Eski plan canlı fırsat olarak sunulmaz. Format/kimlik/tarih bozuksa kayıt korunur ve null döner. Hesap/provider/disk hatası mevcut güvenli SOURCE_TRACE sınıflandırmasıyla loglanır; endpoint'in diğer alanları çalışır.

## UI ve test

Mevcut kart/component/İstanbul formatlama ve XSS escape kullanılır; eksik alan “Yeterli veri yok”. Frontend seviye/indikatör üretmez. Orta/uzun vadeli Hedef1/2, stop, destek/direnç/RR aynen kalır. Teknik bağlam açılır ayrıntıdır.

`tests/test_yarin_plani.py`: kapalı mum, lookahead, seviye/ATR/trend/hacim, durumlar, immutable/atomic/fail-safe/API testleri. `tests/test_tomorrow_plan_ui.cjs`: gerçek sözleşme, mobil mock HTTP, XSS, eksik/hata, eski seviyeler. Railway/gerçek iPhone doğrulaması bu görevde yapılmaz.
