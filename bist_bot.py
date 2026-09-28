import os
import math
import borsapy as bp

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)


TOKEN = os.environ.get("BOT_TOKEN")


print(
    "TOKEN DURUMU:",
    bool(TOKEN),
    "UZUNLUK:",
    len(TOKEN) if TOKEN else 0
)


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def guvenli_float(deger, varsayilan=0.0):
    try:
        sonuc = float(deger)

        if math.isnan(sonuc) or math.isinf(sonuc):
            return varsayilan

        return sonuc

    except Exception:
        return varsayilan


def rsi_yorumu(rsi):

    if rsi < 20:
        return "🔴 Çok güçlü aşırı satım"

    elif rsi < 30:
        return "🟠 Aşırı satım"

    elif rsi < 40:
        return "🟡 Zayıf bölge"

    elif rsi < 60:
        return "🟢 Dengeli bölge"

    elif rsi < 70:
        return "🟢 Güçlü bölge"

    else:
        return "🔴 Aşırı alım"


def trend_yorumu(fiyat, sma20, sma50):

    if fiyat > sma20 and fiyat > sma50 and sma20 > sma50:
        return "🟢 Güçlü yükseliş trendi"

    elif fiyat > sma20 and fiyat > sma50:
        return "🟢 Pozitif trend"

    elif fiyat < sma20 and fiyat < sma50 and sma20 < sma50:
        return "🔴 Güçlü düşüş trendi"

    elif fiyat < sma20 and fiyat < sma50:
        return "🔴 Zayıf trend"

    else:
        return "🟡 Karışık / geçiş bölgesi"


def hacim_yorumu(hacim_orani):

    if hacim_orani >= 200:
        return "🔥 Çok güçlü hacim"

    elif hacim_orani >= 150:
        return "🟢 Güçlü hacim"

    elif hacim_orani >= 120:
        return "🟢 Hacim ortalamanın üzerinde"

    elif hacim_orani >= 100:
        return "🟡 Normalin üzerinde"

    elif hacim_orani >= 80:
        return "🟡 Normal seviyede"

    else:
        return "🔴 Düşük hacim"


def macd_yorumu(macd, signal, macd_yukseliyor, al_kesisim, sat_kesisim):

    if al_kesisim:
        return "🟢 MACD yukarı kesişim"

    if sat_kesisim:
        return "🔴 MACD aşağı kesişim"

    if macd > signal and macd_yukseliyor:
        return "🟢 Pozitif ve yükseliyor"

    if macd > signal:
        return "🟡 Sinyal üzerinde"

    if macd_yukseliyor:
        return "🟡 Negatif ama yükseliyor"

    return "🔴 Negatif / zayıf"


def fiyat_bolge_yorumu(
    fiyat,
    al_alt,
    al_ust,
    sat_alt,
    sat_ust
):

    if al_alt <= fiyat <= al_ust:

        return "🟢 Fiyat hesaplanan giriş bölgesinde"

    elif fiyat < al_alt:

        return "🟡 Fiyat destek/giriş bölgesinin altında"

    elif fiyat < sat_alt:

        return "🟡 Giriş bölgesinin üzerinde, direnç altında"

    elif sat_alt <= fiyat <= sat_ust:

        return "🔴 Fiyat direnç/kâr alma bölgesine yakın"

    else:

        return "🔴 Fiyat hesaplanan direnç üzerinde"


def risk_getiri_hesapla(
    fiyat,
    hedef,
    stop
):

    risk = fiyat - stop
    getiri = hedef - fiyat

    if risk <= 0:
        return 0.0

    if getiri <= 0:
        return 0.0

    return getiri / risk


async def mesaj_parcala_gonder(
    mesaj_gonder,
    metin,
    limit=3900
):

    parcalar = []

    while len(metin) > limit:

        bolum = metin.rfind(
            "\n",
            0,
            limit
        )

        if bolum <= 0:
            bolum = limit

        parcalar.append(
            metin[:bolum]
        )

        metin = metin[bolum:].lstrip()

    if metin:
        parcalar.append(metin)

    for parca in parcalar:

        await mesaj_gonder.reply_text(
            parca
        )


# =========================================================
# TEK HİSSE TEKNİK ANALİZİ
# =========================================================

def hisse_analiz_hesapla(
    sembol,
    period="3mo"
):

    hisse = bp.Ticker(sembol)

    veri = hisse.history(
        period=period
    )

    if (
        veri is None
        or veri.empty
        or len(veri) < 50
    ):

        return None

    gerekli = [
        "Close",
        "High",
        "Low",
        "Open",
        "Volume"
    ]

    if not all(
        kolon in veri.columns
        for kolon in gerekli
    ):

        return None

    kapanis = guvenli_float(
        veri["Close"].iloc[-1]
    )

    onceki = guvenli_float(
        veri["Close"].iloc[-2]
    )

    if kapanis <= 0 or onceki <= 0:
        return None

    gunluk_degisim = (
        (kapanis - onceki)
        / onceki
    ) * 100

    gunluk_yuksek = guvenli_float(
        veri["High"].iloc[-1]
    )

    gunluk_dusuk = guvenli_float(
        veri["Low"].iloc[-1]
    )

    acilis = guvenli_float(
        veri["Open"].iloc[-1]
    )

    # -----------------------------------------------------
    # SMA
    # -----------------------------------------------------

    sma20 = guvenli_float(
        veri["Close"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    sma50 = guvenli_float(
        veri["Close"]
        .rolling(50)
        .mean()
        .iloc[-1]
    )

    if sma20 <= 0 or sma50 <= 0:
        return None

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    delta = veri["Close"].diff()

    kazanc = delta.clip(
        lower=0
    )

    kayip = -delta.clip(
        upper=0
    )

    ort_kazanc = (
        kazanc
        .rolling(14)
        .mean()
    )

    ort_kayip = (
        kayip
        .rolling(14)
        .mean()
    )

    rs = (
        ort_kazanc
        / ort_kayip
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

    rsi_son = guvenli_float(
        rsi.iloc[-1],
        50
    )

    rsi_onceki = guvenli_float(
        rsi.iloc[-2],
        rsi_son
    )

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    ema12 = (
        veri["Close"]
        .ewm(
            span=12,
            adjust=False
        )
        .mean()
    )

    ema26 = (
        veri["Close"]
        .ewm(
            span=26,
            adjust=False
        )
        .mean()
    )

    macd = ema12 - ema26

    macd_signal = (
        macd
        .ewm(
            span=9,
            adjust=False
        )
        .mean()
    )

    macd_son = guvenli_float(
        macd.iloc[-1]
    )

    macd_onceki = guvenli_float(
        macd.iloc[-2]
    )

    macd_signal_son = guvenli_float(
        macd_signal.iloc[-1]
    )

    macd_signal_onceki = guvenli_float(
        macd_signal.iloc[-2]
    )

    macd_yukseliyor = (
        macd_son > macd_onceki
    )

    macd_ustunde = (
        macd_son > macd_signal_son
    )

    macd_al_kesisim = (
        macd_onceki <= macd_signal_onceki
        and
        macd_son > macd_signal_son
    )

    macd_sat_kesisim = (
        macd_onceki >= macd_signal_onceki
        and
        macd_son < macd_signal_son
    )

    # -----------------------------------------------------
    # HACİM
    # -----------------------------------------------------

    hacim = guvenli_float(
        veri["Volume"].iloc[-1]
    )

    hacim20 = guvenli_float(
        veri["Volume"]
        .rolling(20)
        .mean()
        .iloc[-1]
    )

    if hacim20 > 0:

        hacim_orani = (
            hacim / hacim20
        ) * 100

    else:

        hacim_orani = 0

    # -----------------------------------------------------
    # DESTEK / DİRENÇ
    # -----------------------------------------------------

    son20 = veri.tail(20)

    destek = guvenli_float(
        son20["Low"].min()
    )

    direnc = guvenli_float(
        son20["High"].max()
    )

    if destek <= 0 or direnc <= 0:
        return None

    # -----------------------------------------------------
    # ALIM / SATIŞ / HEDEF / STOP
    # -----------------------------------------------------

    al_alt = destek * 0.99
    al_ust = destek * 1.03

    hedef1 = kapanis + (
        (direnc - kapanis) * 0.50
    )

    hedef2 = direnc

    stop = destek * 0.97

    sat_alt = direnc * 0.97
    sat_ust = direnc

    risk_getiri = risk_getiri_hesapla(
        kapanis,
        hedef1,
        stop
    )

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    trend = trend_yorumu(
        kapanis,
        sma20,
        sma50
    )

    # -----------------------------------------------------
    # TEKNİK PUAN
    # -----------------------------------------------------

    puan = 50

    nedenler = []

    if kapanis > sma20:

        puan += 10

        nedenler.append(
            "Fiyat SMA20 üzerinde"
        )

    else:

        puan -= 10

        nedenler.append(
            "Fiyat SMA20 altında"
        )

    if kapanis > sma50:

        puan += 10

        nedenler.append(
            "Fiyat SMA50 üzerinde"
        )

    else:

        puan -= 10

        nedenler.append(
            "Fiyat SMA50 altında"
        )

    if 50 <= rsi_son < 70:

        puan += 10

        nedenler.append(
            "RSI güçlü/dengeli bölgede"
        )

    elif rsi_son >= 70:

        puan -= 5

        nedenler.append(
            "RSI aşırı alım bölgesinde"
        )

    elif rsi_son < 30:

        puan += 5

        nedenler.append(
            "RSI aşırı satım bölgesinde"
        )

    else:

        nedenler.append(
            "RSI nötr bölgede"
        )

    if macd_ustunde:

        puan += 10

        nedenler.append(
            "MACD sinyal çizgisinin üzerinde"
        )

    else:

        puan -= 10

        nedenler.append(
            "MACD sinyal çizgisinin altında"
        )

    if macd_al_kesisim:

        puan += 10

        nedenler.append(
            "MACD yukarı kesişim yaptı"
        )

    elif macd_sat_kesisim:

        puan -= 10

        nedenler.append(
            "MACD aşağı kesişim yaptı"
        )

    if macd_yukseliyor:

        puan += 5

        nedenler.append(
            "MACD yükseliyor"
        )

    else:

        puan -= 5

        nedenler.append(
            "MACD düşüyor"
        )

    if hacim_orani >= 150:

        puan += 10

        nedenler.append(
            "Hacim güçlü"
        )

    elif hacim_orani >= 100:

        puan += 5

        nedenler.append(
            "Hacim ortalamanın üzerinde"
        )

    else:

        puan -= 5

        nedenler.append(
            "Hacim 20G ortalamasının altında"
        )

    if gunluk_degisim > 0:

        puan += 5

        nedenler.append(
            "Günlük momentum pozitif"
        )

    else:

        puan -= 5

        nedenler.append(
            "Günlük momentum negatif"
        )

    puan = max(
        0,
        min(100, puan)
    )

    return {
        "sembol": sembol,
        "fiyat": kapanis,
        "onceki": onceki,
        "degisim": gunluk_degisim,
        "yuksek": gunluk_yuksek,
        "dusuk": gunluk_dusuk,
        "acilis": acilis,
        "hacim": hacim,
        "hacim20": hacim20,
        "hacim_orani": hacim_orani,
        "sma20": sma20,
        "sma50": sma50,
        "rsi": rsi_son,
        "rsi_onceki": rsi_onceki,
        "macd": macd_son,
        "macd_signal": macd_signal_son,
        "macd_yukseliyor": macd_yukseliyor,
        "macd_ustunde": macd_ustunde,
        "macd_al_kesisim": macd_al_kesisim,
        "macd_sat_kesisim": macd_sat_kesisim,
        "destek": destek,
        "direnc": direnc,
        "al_alt": al_alt,
        "al_ust": al_ust,
        "sat_alt": sat_alt,
        "sat_ust": sat_ust,
        "hedef1": hedef1,
        "hedef2": hedef2,
        "stop": stop,
        "risk_getiri": risk_getiri,
        "trend": trend,
        "puan": puan,
        "nedenler": nedenler
    }


# =========================================================
# AGRESİF ADAY KRİTERİ
# =========================================================

def agresif_mi(a):

    puan = a["puan"]
    rsi = a["rsi"]
    hacim = a["hacim_orani"]
    macd_yukseliyor = a["macd_yukseliyor"]
    macd_kesisim = a["macd_al_kesisim"]

    if puan >= 45:
        return True

    if (
        hacim >= 150
        and rsi < 35
        and macd_yukseliyor
    ):
        return True

    if (
        macd_kesisim
        and hacim >= 120
    ):
        return True

    return False


# =========================================================
# YARIN İÇİN POTANSİYEL PUANI
# =========================================================

def yarin_potansiyel_hesapla(a):

    fiyat = a["fiyat"]
    sma20 = a["sma20"]
    sma50 = a["sma50"]
    rsi = a["rsi"]
    hacim = a["hacim_orani"]
    degisim = a["degisim"]

    macd_yukseliyor = a["macd_yukseliyor"]
    macd_ustunde = a["macd_ustunde"]
    macd_kesisim = a["macd_al_kesisim"]

    puan = 50
    nedenler = []

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    if fiyat > sma20:

        puan += 8
        nedenler.append(
            "Fiyat SMA20 üzerinde"
        )

    else:

        puan -= 5

    if fiyat > sma50:

        puan += 8
        nedenler.append(
            "Fiyat SMA50 üzerinde"
        )

    else:

        puan -= 5

    if sma20 > sma50:

        puan += 8
        nedenler.append(
            "SMA20, SMA50 üzerinde"
        )

    else:

        puan -= 5

    # -----------------------------------------------------
    # MACD
    # -----------------------------------------------------

    if macd_ustunde:

        puan += 10
        nedenler.append(
            "MACD sinyal üzerinde"
        )

    if macd_yukseliyor:

        puan += 8
        nedenler.append(
            "MACD yükseliş momentumunda"
        )

    if macd_kesisim:

        puan += 12
        nedenler.append(
            "Yeni MACD yukarı kesişimi"
        )

    # -----------------------------------------------------
    # HACİM
    # -----------------------------------------------------

    if hacim >= 200:

        puan += 12
        nedenler.append(
            "Hacim çok güçlü"
        )

    elif hacim >= 150:

        puan += 10
        nedenler.append(
            "Hacim güçlü"
        )

    elif hacim >= 120:

        puan += 7
        nedenler.append(
            "Hacim ortalamanın üzerinde"
        )

    elif hacim >= 100:

        puan += 4

    else:

        puan -= 3

    # -----------------------------------------------------
    # RSI
    # -----------------------------------------------------

    # Yarın için modelde orta RSI daha dengeli kabul edilir.

    if 45 <= rsi <= 60:

        puan += 10

        nedenler.append(
            "RSI dengeli ve momentum için uygun bölgede"
        )

    elif 35 <= rsi < 45:

        puan += 8

        nedenler.append(
            "RSI düşük ancak toparlanma alanında"
        )

    elif 60 < rsi <= 70:

        puan += 5

        nedenler.append(
            "RSI güçlü ancak yükselmiş bölgede"
        )

    elif 30 <= rsi < 35:

        puan += 4

        nedenler.append(
            "RSI düşük bölgede"
        )

    elif rsi < 30:

        puan += 2

        nedenler.append(
            "RSI aşırı satımda; tepki ihtimali izlenebilir"
        )

    elif rsi > 70:

        puan -= 10

        nedenler.append(
            "RSI aşırı alımda; kısa vadeli risk yüksek"
        )

    # -----------------------------------------------------
    # GÜNLÜK HAREKET
    # -----------------------------------------------------

    if 0 <= degisim <= 3:

        puan += 6

        nedenler.append(
            "Günlük hareket kontrollü pozitif"
        )

    elif 3 < degisim <= 5:

        puan += 2

        nedenler.append(
            "Günlük momentum güçlü"
        )

    elif degisim > 5:

        puan -= 5

        nedenler.append(
            "Günlük yükseliş fazla; takipte kalma riski"
        )

    elif -3 <= degisim < 0:

        puan += 3

        nedenler.append(
            "Geri çekilme sonrası toparlanma alanı"
        )

    elif degisim < -5:

        puan -= 3

    # -----------------------------------------------------
    # DİRENCE KADAR ALAN
    # -----------------------------------------------------

    if fiyat < a["direnc"]:

        direnç_mesafe = (
            (a["direnc"] - fiyat)
            / fiyat
        ) * 100

        if direnç_mesafe >= 15:

            puan += 8

            nedenler.append(
                "Dirence kadar geniş teknik alan"
            )

        elif direnç_mesafe >= 8:

            puan += 5

            nedenler.append(
                "Dirence kadar makul alan"
            )

        elif direnç_mesafe >= 3:

            puan += 2

        else:

            puan -= 4

            nedenler.append(
                "Dirence çok yakın"
            )

    # -----------------------------------------------------
    # RİSK / GETİRİ
    # -----------------------------------------------------

    if a["risk_getiri"] >= 3:

        puan += 7

        nedenler.append(
            "Hesaplanan hedefe göre risk/getiri güçlü"
        )

    elif a["risk_getiri"] >= 2:

        puan += 4

    elif 0 < a["risk_getiri"] < 1:

        puan -= 5

    # -----------------------------------------------------
    # 0-100
    # -----------------------------------------------------

    puan = max(
        0,
        min(100, puan)
    )

    return puan, nedenler


# =========================================================
# BIST TARAMA
# =========================================================

def bist_hisseleri_getir():

    sirketler = bp.companies()

    if (
        sirketler is None
        or sirketler.empty
    ):

        return []

    if "ticker" in sirketler.columns:

        hisseler = (
            sirketler["ticker"]
            .dropna()
            .astype(str)
            .str.upper()
            .str.strip()
            .tolist()
        )

    elif "symbol" in sirketler.columns:

        hisseler = (
            sirketler["symbol"]
            .dropna()
            .astype(str)
            .str.upper()
            .str.strip()
            .tolist()
        )

    else:

        return []

    return list(
        dict.fromkeys(hisseler)
    )


def bist_tara():

    hisseler = bist_hisseleri_getir()

    adaylar = []

    taranan = 0

    for sembol in hisseler:

        taranan += 1

        try:

            analiz = hisse_analiz_hesapla(
                sembol,
                period="3mo"
            )

            if analiz is None:
                continue

            if agresif_mi(analiz):

                yarin_puan, yarin_nedenler = (
                    yarin_potansiyel_hesapla(
                        analiz
                    )
                )

                analiz["yarin_puan"] = yarin_puan

                analiz["yarin_nedenler"] = (
                    yarin_nedenler
                )

                adaylar.append(
                    analiz
                )

        except Exception:

            continue

    return (
        taranan,
        adaylar
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [

        [
            InlineKeyboardButton(
                "📈 Hisse Özeti",
                callback_data="ozet"
            )
        ],

        [
            InlineKeyboardButton(
                "📡 Gelişmiş Sinyal",
                callback_data="sinyal"
            )
        ],

        [
            InlineKeyboardButton(
                "🔥 Anlık Agresifler",
                callback_data="anlik_agresif"
            )
        ],

        [
            InlineKeyboardButton(
                "🏆 Yarın İçin TOP 10",
                callback_data="yarin_top10"
            )
        ]

    ]

    await update.message.reply_text(
        "🤖 BIST AI TERMINAL\n\n"
        "Bir işlem seç:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# BUTONLAR
# =========================================================

async def buton(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "ozet":

        context.user_data[
            "hisse_bekleniyor"
        ] = True

        context.user_data[
            "mod"
        ] = "ozet"

        await query.message.reply_text(
            "📈 DETAYLI HİSSE ÖZETİ\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: PSGYO"
        )

    elif query.data == "sinyal":

        context.user_data[
            "hisse_bekleniyor"
        ] = True

        context.user_data[
            "mod"
        ] = "sinyal"

        await query.message.reply_text(
            "📡 GELİŞMİŞ SİNYAL ANALİZİ\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: PSGYO"
        )

    elif query.data == "anlik_agresif":

        await anlik_agresif_tarama(
            update,
            context
        )

    elif query.data == "yarin_top10":

        await yarin_top10_tarama(
            update,
            context
        )


# =========================================================
# ANLIK AGRESİFLER
# =========================================================

async def anlik_agresif_tarama(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mesaj_gonder = (
        update.callback_query.message
    )

    await mesaj_gonder.reply_text(
        "🔥 ANLIK AGRESİF TARAMA BAŞLIYOR...\n\n"
        "📊 Tüm BIST yeniden taranıyor.\n"
        "📈 RSI / MACD / SMA / Hacim hesaplanıyor.\n"
        "⏳ Tarama biraz sürebilir..."
    )

    try:

        taranan, adaylar = bist_tara()

        adaylar.sort(
            key=lambda x: (
                x["puan"],
                x["hacim_orani"]
            ),
            reverse=True
        )

        if not adaylar:

            await mesaj_gonder.reply_text(
                "🔎 TARAMA TAMAMLANDI.\n\n"
                f"📊 Taranan: {taranan}\n"
                "🔥 Agresif aday bulunamadı."
            )

            return

        mesaj = (
            "🔥 ANLIK AGRESİF HİSSELER\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📊 Taranan: {taranan} hisse\n"
            f"🔥 Agresif aday: {len(adaylar)}\n\n"
            "Aşağıdaki liste o anki mevcut "
            "veriye göre oluşturulmuştur.\n\n"
        )

        for sira, a in enumerate(
            adaylar,
            1
        ):

            macd_durum = macd_yorumu(
                a["macd"],
                a["macd_signal"],
                a["macd_yukseliyor"],
                a["macd_al_kesisim"],
                a["macd_sat_kesisim"]
            )

            mesaj += (
                f"🔥 {sira}. {a['sembol']}\n"
                f"⭐ Teknik Puan: {a['puan']}/100\n"
                f"💰 Fiyat: {a['fiyat']:.2f} TL\n"
                f"📈 Günlük: {a['degisim']:+.2f}%\n"
                f"RSI: {a['rsi']:.2f} "
                f"({rsi_yorumu(a['rsi'])})\n"
                f"📦 Hacim: {a['hacim']:,.0f} "
                f"({a['hacim_orani']:.1f}% / 20G)\n"
                f"📊 MACD: {macd_durum}\n"
                f"📈 Trend: {a['trend']}\n"
                f"📉 SMA20: {a['sma20']:.2f} TL\n"
                f"📉 SMA50: {a['sma50']:.2f} TL\n"
                f"🟢 Destek: {a['destek']:.2f} TL\n"
                f"🔴 Direnç: {a['direnc']:.2f} TL\n"
                f"💰 Giriş bölgesi: "
                f"{a['al_alt']:.2f} - {a['al_ust']:.2f} TL\n"
                f"🔴 Satış/kâr bölgesi: "
                f"{a['sat_alt']:.2f} - {a['sat_ust']:.2f} TL\n"
                f"🎯 Hedef 1: {a['hedef1']:.2f} TL\n"
                f"🎯 Hedef 2: {a['hedef2']:.2f} TL\n"
                f"🛑 Stop: {a['stop']:.2f} TL\n"
                f"⚖️ Risk/Getiri: "
                f"{a['risk_getiri']:.2f}\n"
                f"📌 Konum: "
                f"{fiyat_bolge_yorumu(a['fiyat'], a['al_alt'], a['al_ust'], a['sat_alt'], a['sat_ust'])}\n"
            )

            if a["nedenler"]:

                mesaj += "\n🔎 Nedenler:\n"

                for neden in a["nedenler"][:6]:

                    mesaj += (
                        f"• {neden}\n"
                    )

            mesaj += (
                "\n"
                "────────────────\n\n"
            )

        mesaj += (
            "⚠️ Teknik puanlar algoritmik "
            "göstergelere göre hesaplanır.\n"
            "⚠️ Agresif aday olması yükseliş "
            "garantisi anlamına gelmez.\n"
            "⚠️ Giriş, hedef ve stop seviyeleri "
            "hesaplanmış teknik seviyelerdir.\n"
            "⚠️ Yatırım tavsiyesi değildir."
        )

        await mesaj_parcala_gonder(
            mesaj_gonder,
            mesaj
        )

    except Exception as e:

        await mesaj_gonder.reply_text(
            f"❌ Anlık tarama hatası:\n{e}"
        )


# =========================================================
# YARIN İÇİN TOP 10
# =========================================================

async def yarin_top10_tarama(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    mesaj_gonder = (
        update.callback_query.message
    )

    await mesaj_gonder.reply_text(
        "🏆 YARIN İÇİN TOP 10 TARAMASI BAŞLIYOR...\n\n"
        "📊 Tüm BIST taranıyor.\n"
        "🧠 Ayrı bir teknik potansiyel modeli çalışıyor.\n"
        "📈 Trend + RSI + MACD + Hacim + direnç alanı + risk/getiri hesaplanıyor.\n"
        "⏳ Biraz sürebilir..."
    )

    try:

        taranan, adaylar = bist_tara()

        if not adaylar:

            await mesaj_gonder.reply_text(
                "🔎 Tarama tamamlandı.\n\n"
                f"📊 Taranan: {taranan}\n"
                "🏆 TOP 10 için uygun agresif aday bulunamadı."
            )

            return

        # -------------------------------------------------
        # YARIN MODELİNE GÖRE SIRALA
        # -------------------------------------------------

        adaylar.sort(
            key=lambda x: (
                x["yarin_puan"],
                x["puan"],
                x["hacim_orani"]
            ),
            reverse=True
        )

        top10 = adaylar[:10]

        mesaj = (
            "🏆 YARIN İÇİN TOP 10\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📊 Taranan: {taranan} hisse\n"
            f"🔥 Agresif aday havuzu: {len(adaylar)}\n\n"
            "🧠 Bu sıralama, bir sonraki işlem "
            "seansı için algoritmik teknik "
            "potansiyel puanına göre hazırlanmıştır.\n"
            "Kesin yükseliş tahmini değildir.\n\n"
        )

        for sira, a in enumerate(
            top10,
            1
        ):

            macd_durum = macd_yorumu(
                a["macd"],
                a["macd_signal"],
                a["macd_yukseliyor"],
                a["macd_al_kesisim"],
                a["macd_sat_kesisim"]
            )

            mesaj += (
                f"🏆 {sira}. {a['sembol']}\n"
                f"🧠 Yarın Teknik Potansiyel: "
                f"{a['yarin_puan']}/100\n"
                f"⭐ Anlık Teknik Puan: "
                f"{a['puan']}/100\n\n"

                f"💰 Fiyat: "
                f"{a['fiyat']:.2f} TL\n"
                f"📈 Günlük: "
                f"{a['degisim']:+.2f}%\n"
                f"RSI: {a['rsi']:.2f} "
                f"({rsi_yorumu(a['rsi'])})\n"
                f"📦 Hacim: "
                f"{a['hacim_orani']:.1f}% / 20G\n"
                f"📊 MACD: {macd_durum}\n"
                f"📈 Trend: {a['trend']}\n\n"

                f"🟢 Destek: "
                f"{a['destek']:.2f} TL\n"
                f"🔴 Direnç: "
                f"{a['direnc']:.2f} TL\n"

                f"💰 Giriş bölgesi: "
                f"{a['al_alt']:.2f} - "
                f"{a['al_ust']:.2f} TL\n"

                f"🔴 Satış/kâr bölgesi: "
                f"{a['sat_alt']:.2f} - "
                f"{a['sat_ust']:.2f} TL\n"

                f"🎯 Hedef 1: "
                f"{a['hedef1']:.2f} TL\n"

                f"🎯 Hedef 2: "
                f"{a['hedef2']:.2f} TL\n"

                f"🛑 Stop: "
                f"{a['stop']:.2f} TL\n"

                f"⚖️ Risk/Getiri: "
                f"{a['risk_getiri']:.2f}\n"

                f"📌 Fiyat konumu: "
                f"{fiyat_bolge_yorumu(a['fiyat'], a['al_alt'], a['al_ust'], a['sat_alt'], a['sat_ust'])}\n"
            )

            if a["yarin_nedenler"]:

                mesaj += (
                    "\n🧠 Yarın modelinin nedenleri:\n"
                )

                for neden in a[
                    "yarin_nedenler"
                ][:7]:

                    mesaj += (
                        f"• {neden}\n"
                    )

            mesaj += (
                "\n"
                "────────────────\n\n"
            )

        # -------------------------------------------------
        # TÜM AGRESİF ADAYLAR
        # -------------------------------------------------

        mesaj += (
            "🔥 TÜM AGRESİF ADAYLAR\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Toplam: {len(adaylar)} hisse\n\n"
        )

        for sira, a in enumerate(
            adaylar,
            1
        ):

            mesaj += (
                f"🔥 {sira}. {a['sembol']}\n"
                f"🧠 Yarın Puanı: "
                f"{a['yarin_puan']}/100\n"
                f"⭐ Teknik Puan: "
                f"{a['puan']}/100\n"
                f"💰 Fiyat: "
                f"{a['fiyat']:.2f} TL\n"
                f"📈 Günlük: "
                f"{a['degisim']:+.2f}%\n"
                f"RSI: "
                f"{a['rsi']:.2f}\n"
                f"📦 Hacim: "
                f"%{a['hacim_orani']:.1f}\n"
                f"📊 MACD: "
                f"{macd_yorumu(a['macd'], a['macd_signal'], a['macd_yukseliyor'], a['macd_al_kesisim'], a['macd_sat_kesisim'])}\n"
                f"🟢 Destek: "
                f"{a['destek']:.2f} TL\n"
                f"🔴 Direnç: "
                f"{a['direnc']:.2f} TL\n"
                f"💰 Giriş: "
                f"{a['al_alt']:.2f} - "
                f"{a['al_ust']:.2f} TL\n"
                f"🔴 Satış: "
                f"{a['sat_alt']:.2f} - "
                f"{a['sat_ust']:.2f} TL\n"
                f"🎯 H1: "
                f"{a['hedef1']:.2f} TL\n"
                f"🎯 H2: "
                f"{a['hedef2']:.2f} TL\n"
                f"🛑 Stop: "
                f"{a['stop']:.2f} TL\n"
                f"⚖️ R/G: "
                f"{a['risk_getiri']:.2f}\n"
            )

            if a["yarin_nedenler"]:

                mesaj += (
                    "🔎 Nedenler:\n"
                )

                for neden in a[
                    "yarin_nedenler"
                ][:5]:

                    mesaj += (
                        f"• {neden}\n"
                    )

            mesaj += (
                "\n────────────────\n\n"
            )

        mesaj += (
            "⚠️ Yarın Teknik Potansiyel puanı "
            "algoritmik bir sıralamadır.\n"
            "⚠️ Puan yüksekliği kesin yükseliş "
            "veya belirli bir getiri garantisi değildir.\n"
            "⚠️ Teknik seviyeler geçmiş fiyat "
            "verisinden hesaplanmıştır.\n"
            "⚠️ Yatırım tavsiyesi değildir."
        )

        await mesaj_parcala_gonder(
            mesaj_gonder,
            mesaj
        )

    except Exception as e:

        await mesaj_gonder.reply_text(
            f"❌ TOP 10 tarama hatası:\n{e}"
        )


# =========================================================
# TEK HİSSE
# =========================================================

async def hisse_oku(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get(
        "hisse_bekleniyor"
    ):

        return

    sembol = (
        update.message.text
        .strip()
        .upper()
    )

    mod = context.user_data.get(
        "mod"
    )

    try:

        a = hisse_analiz_hesapla(
            sembol,
            period="3mo"
        )

        if a is None:

            await update.message.reply_text(
                "❌ Bu hisse için yeterli veri bulunamadı.\n\n"
                "Örnek kullanım: PSGYO"
            )

            return

        # =================================================
        # DETAYLI HİSSE ÖZETİ
        # =================================================

        if mod == "ozet":

            mesaj = (
                f"📊 {sembol} DETAYLI HİSSE ÖZETİ\n"
                f"━━━━━━━━━━━━━━\n\n"

                f"💰 SON DURUM\n"
                f"Fiyat: "
                f"{a['fiyat']:.2f} TL\n"
                f"📈 Günlük: "
                f"{a['degisim']:+.2f}%\n"
                f"🔺 Günlük Yüksek: "
                f"{a['yuksek']:.2f} TL\n"
                f"🔻 Günlük Düşük: "
                f"{a['dusuk']:.2f} TL\n"
                f"🔵 Açılış: "
                f"{a['acilis']:.2f} TL\n"
                f"📦 Hacim: "
                f"{a['hacim']:,.0f}\n\n"

                f"📊 TEKNİK GÖSTERGELER\n"
                f"━━━━━━━━━━━━━━\n"
                f"📈 SMA20: "
                f"{a['sma20']:.2f} TL\n"
                f"📈 SMA50: "
                f"{a['sma50']:.2f} TL\n"
                f"📌 Trend: "
                f"{a['trend']}\n\n"

                f"RSI(14): "
                f"{a['rsi']:.2f}\n"
                f"➡️ RSI yorumu: "
                f"{rsi_yorumu(a['rsi'])}\n\n"

                f"MACD: "
                f"{a['macd']:.4f}\n"
                f"MACD Sinyal: "
                f"{a['macd_signal']:.4f}\n"
                f"📊 MACD yorumu: "
                f"{macd_yorumu(a['macd'], a['macd_signal'], a['macd_yukseliyor'], a['macd_al_kesisim'], a['macd_sat_kesisim'])}\n\n"

                f"📦 HACİM ANALİZİ\n"
                f"Mevcut: "
                f"{a['hacim']:,.0f}\n"
                f"20G Ortalama: "
                f"{a['hacim20']:,.0f}\n"
                f"Hacim Oranı: "
                f"%{a['hacim_orani']:.1f}\n"
                f"➡️ "
                f"{hacim_yorumu(a['hacim_orani'])}\n\n"

                f"📍 DESTEK / DİRENÇ\n"
                f"🟢 Destek: "
                f"{a['destek']:.2f} TL\n"
                f"🔴 Direnç: "
                f"{a['direnc']:.2f} TL\n\n"

                f"💰 TEKNİK GİRİŞ BÖLGESİ\n"
                f"{a['al_alt']:.2f} - "
                f"{a['al_ust']:.2f} TL\n"
                f"{fiyat_bolge_yorumu(a['fiyat'], a['al_alt'], a['al_ust'], a['sat_alt'], a['sat_ust'])}\n\n"

                f"🎯 HEDEFLER\n"
                f"1. Hedef: "
                f"{a['hedef1']:.2f} TL\n"
                f"2. Hedef: "
                f"{a['hedef2']:.2f} TL\n\n"

                f"🔴 SATIŞ / KÂR ALMA BÖLGESİ\n"
                f"{a['sat_alt']:.2f} - "
                f"{a['sat_ust']:.2f} TL\n\n"

                f"🛑 STOP / RİSK SEVİYESİ\n"
                f"{a['stop']:.2f} TL\n"
                f"⚖️ Risk/Getiri: "
                f"{a['risk_getiri']:.2f}\n\n"

                f"⭐ TEKNİK PUAN\n"
                f"{a['puan']}/100\n\n"

                f"🧠 TEKNİK YORUM\n"
            )

            for neden in a["nedenler"]:

                mesaj += (
                    f"• {neden}\n"
                )

            if a["rsi"] < 30:

                mesaj += (
                    "\n⚠️ RSI aşırı satım bölgesinde. "
                    "Bu durum tepki ihtimalini artırabilir "
                    "ancak düşüşün sona erdiği anlamına gelmez.\n"
                )

            elif a["rsi"] > 70:

                mesaj += (
                    "\n⚠️ RSI aşırı alım bölgesinde. "
                    "Kısa vadeli geri çekilme riski izlenebilir.\n"
                )

            mesaj += (
                "\n⚠️ Giriş, hedef, satış ve stop seviyeleri "
                "algoritmik teknik seviyelerdir.\n"
                "⚠️ Kesin al/sat sonucu değildir."
            )

        # =================================================
        # GELİŞMİŞ SİNYAL
        # =================================================

        else:

            puan = a["puan"]

            if (
                a["rsi"] < 25
                and a["macd_yukseliyor"]
            ):

                sinyal = (
                    "🟠 AŞIRI SATIM / "
                    "TEPKİ ADAYI"
                )

            elif (
                a["rsi"] < 25
                and puan <= 35
            ):

                sinyal = (
                    "🟠 AŞIRI SATIM / "
                    "RİSKLİ BÖLGE"
                )

            elif puan >= 70:

                sinyal = "🟢 GÜÇLÜ TEKNİK ADAY"

            elif puan <= 35:

                sinyal = (
                    "🔴 ZAYIF / RİSKLİ BÖLGE"
                )

            else:

                sinyal = "🟡 BEKLE / İZLE"

            mesaj = (
                f"📡 {sembol} GELİŞMİŞ SİNYAL\n"
                f"━━━━━━━━━━━━━━\n\n"

                f"💰 Fiyat: "
                f"{a['fiyat']:.2f} TL\n"
                f"📈 Günlük: "
                f"{a['degisim']:+.2f}%\n\n"

                f"🎯 SİNYAL\n"
                f"{sinyal}\n\n"

                f"⭐ TEKNİK PUAN: "
                f"{puan}/100\n\n"

                f"📊 GÖSTERGELER\n"
                f"RSI(14): "
                f"{a['rsi']:.2f}\n"
                f"RSI: "
                f"{rsi_yorumu(a['rsi'])}\n\n"

                f"SMA20: "
                f"{a['sma20']:.2f} TL\n"
                f"SMA50: "
                f"{a['sma50']:.2f} TL\n"
                f"Trend: "
                f"{a['trend']}\n\n"

                f"MACD: "
                f"{a['macd']:.4f}\n"
                f"MACD Sinyal: "
                f"{a['macd_signal']:.4f}\n"
                f"MACD: "
                f"{macd_yorumu(a['macd'], a['macd_signal'], a['macd_yukseliyor'], a['macd_al_kesisim'], a['macd_sat_kesisim'])}\n\n"

                f"📦 HACİM\n"
                f"Mevcut: "
                f"{a['hacim']:,.0f}\n"
                f"20G Ortalama: "
                f"{a['hacim20']:,.0f}\n"
                f"Oran: "
                f"%{a['hacim_orani']:.1f}\n"
                f"{hacim_yorumu(a['hacim_orani'])}\n\n"

                f"📍 DESTEK / DİRENÇ\n"
                f"🟢 Destek: "
                f"{a['destek']:.2f} TL\n"
                f"🔴 Direnç: "
                f"{a['direnc']:.2f} TL\n\n"

                f"💰 GİRİŞ BÖLGESİ\n"
                f"{a['al_alt']:.2f} - "
                f"{a['al_ust']:.2f} TL\n\n"

                f"🔴 SATIŞ / KÂR ALMA\n"
                f"{a['sat_alt']:.2f} - "
                f"{a['sat_ust']:.2f} TL\n\n"

                f"🎯 HEDEFLER\n"
                f"Hedef 1: "
                f"{a['hedef1']:.2f} TL\n"
                f"Hedef 2: "
                f"{a['hedef2']:.2f} TL\n\n"

                f"🛑 STOP\n"
                f"{a['stop']:.2f} TL\n\n"

                f"⚖️ RİSK / GETİRİ\n"
                f"{a['risk_getiri']:.2f}\n\n"

                f"🔎 GEREKÇELER\n"
            )

            for neden in a["nedenler"]:

                mesaj += (
                    f"• {neden}\n"
                )

            mesaj += (
                "\n"
                "⚠️ Teknik göstergeler geçmiş ve mevcut "
                "fiyat verisine dayalıdır.\n"
                "⚠️ Sinyal kesin al/sat sonucu değildir.\n"
                "⚠️ Yatırım tavsiyesi değildir."
            )

        await update.message.reply_text(
            mesaj
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Hata:\n{e}"
        )

    context.user_data[
        "hisse_bekleniyor"
    ] = False

    context.user_data[
        "mod"
    ] = None


# =========================================================
# TELEGRAM UYGULAMASI
# =========================================================

app = (
    Application
    .builder()
    .token(TOKEN)
    .build()
)


app.add_handler(
    CommandHandler(
        "start",
        start
    )
)


app.add_handler(
    CallbackQueryHandler(
        buton
    )
)


app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        hisse_oku
    )
)


print(
    "BIST AI Terminal çalışıyor..."
)


app.run_polling()
