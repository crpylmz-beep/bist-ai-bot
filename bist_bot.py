import os
import math
import time
import borsapy as bp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================

def guvenli_float(x, varsayilan=0.0):
    try:
        if x is None:
            return varsayilan
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return varsayilan
        return v
    except Exception:
        return varsayilan


def rsi_hesapla(close, periyot=14):
    delta = close.diff()

    kazanc = delta.clip(lower=0)
    kayip = -delta.clip(upper=0)

    ort_kazanc = kazanc.rolling(periyot).mean()
    ort_kayip = kayip.rolling(periyot).mean()

    rs = ort_kazanc / ort_kayip.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    return rsi


def rsi_yorumu(rsi):
    if rsi < 25:
        return "⚠️ Çok güçlü aşırı satım"
    elif rsi < 30:
        return "🟠 Aşırı satım"
    elif rsi < 45:
        return "🟡 Zayıf"
    elif rsi < 55:
        return "⚪ Nötr"
    elif rsi < 70:
        return "🟢 Pozitif"
    else:
        return "🔴 Aşırı alım"


def trend_yorumu(fiyat, sma20, sma50):
    if fiyat > sma20 > sma50:
        return "🟢 Güçlü yükseliş trendi"

    if fiyat > sma20 and fiyat > sma50:
        return "🟢 Pozitif trend"

    if fiyat < sma20 < sma50:
        return "🔴 Güçlü düşüş trendi"

    if fiyat < sma20 and fiyat < sma50:
        return "🔴 Negatif trend"

    return "🟡 Karışık trend"


def hacim_yorumu(orani):
    if orani >= 200:
        return "🔥 Çok güçlü hacim"
    elif orani >= 130:
        return "🟢 Güçlü hacim"
    elif orani >= 100:
        return "🟡 Ortalama üstü hacim"
    else:
        return "⚪ Zayıf hacim"


def macd_yorumu(macd, signal, hist):
    if macd > signal and hist > 0:
        return "🟢 MACD pozitif momentum"

    if macd > signal:
        return "🟢 MACD sinyal üzerinde"

    if macd < signal and hist < 0:
        return "🔴 MACD negatif momentum"

    return "🟡 MACD zayıf/nötr"


def mesaj_parcala_gonder(update, mesaj, limit=3900):
    parcalar = []

    while len(mesaj) > limit:
        kes = mesaj.rfind("\n", 0, limit)

        if kes <= 0:
            kes = limit

        parcalar.append(mesaj[:kes])
        mesaj = mesaj[kes:].lstrip()

    if mesaj:
        parcalar.append(mesaj)

    return parcalar


# =========================================================
# TEKNİK ANALİZ
# =========================================================

def hisse_analiz_hesapla(sembol, period="6mo"):

    hisse = bp.Ticker(sembol)
    veri = hisse.history(period=period)

    if veri is None or veri.empty:
        return None

    if len(veri) < 60:
        return None

    try:
        close = veri["Close"]
        volume = veri["Volume"]

        son = veri.iloc[-1]
        onceki = veri.iloc[-2]

        fiyat = guvenli_float(son["Close"])
        onceki_fiyat = guvenli_float(onceki["Close"])

        if fiyat <= 0 or onceki_fiyat <= 0:
            return None

        gunluk_degisim = ((fiyat - onceki_fiyat) / onceki_fiyat) * 100

        yuksek = guvenli_float(son["High"])
        dusuk = guvenli_float(son["Low"])
        acilis = guvenli_float(son["Open"])
        hacim = guvenli_float(son["Volume"])

        sma20 = guvenli_float(close.rolling(20).mean().iloc[-1])
        sma50 = guvenli_float(close.rolling(50).mean().iloc[-1])

        hacim20 = guvenli_float(
            volume.rolling(20).mean().iloc[-1]
        )

        hacim_orani = (
            (hacim / hacim20) * 100
            if hacim20 > 0
            else 0
        )

        rsi = rsi_hesapla(close)
        rsi_son = guvenli_float(rsi.iloc[-1])

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()

        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        histogram = macd - signal

        macd_son = guvenli_float(macd.iloc[-1])
        signal_son = guvenli_float(signal.iloc[-1])
        hist_son = guvenli_float(histogram.iloc[-1])

        macd_onceki = guvenli_float(macd.iloc[-2])
        signal_onceki = guvenli_float(signal.iloc[-2])

        yukari_kesisim = (
            macd_onceki <= signal_onceki
            and macd_son > signal_son
        )

        asagi_kesisim = (
            macd_onceki >= signal_onceki
            and macd_son < signal_son
        )

        # -------------------------------------------------
        # DESTEK / DİRENÇ
        # -------------------------------------------------

        son20 = veri.tail(20)

        destek = guvenli_float(
            son20["Low"].min(),
            dusuk
        )

        direnç = guvenli_float(
            son20["High"].max(),
            yuksek
        )

        son60 = veri.tail(60)

        direnç60 = guvenli_float(
            son60["High"].max(),
            direnç
        )

        # -------------------------------------------------
        # ATR
        # -------------------------------------------------

        onceki_kapanis = close.shift(1)

        tr1 = veri["High"] - veri["Low"]
        tr2 = (veri["High"] - onceki_kapanis).abs()
        tr3 = (veri["Low"] - onceki_kapanis).abs()

        true_range = tr1.combine(tr2, max)
        true_range = true_range.combine(tr3, max)

        atr14 = guvenli_float(
            true_range.rolling(14).mean().iloc[-1],
            fiyat * 0.03
        )

        if atr14 <= 0:
            atr14 = fiyat * 0.03

        # -------------------------------------------------
        # HEDEF / STOP
        # -------------------------------------------------

        teknik_giris_alt = max(
            destek,
            fiyat - atr14
        )

        teknik_giris_ust = min(
            fiyat + atr14 * 0.5,
            direnç
        )

        hedef1 = max(
            direnç,
            fiyat + atr14 * 1.5
        )

        hedef2 = max(
            direnç60,
            hedef1 + atr14
        )

        stop = max(
            0.01,
            min(
                destek - atr14 * 0.25,
                fiyat - atr14 * 1.5
            )
        )

        risk = fiyat - stop
        getiri = hedef1 - fiyat

        risk_getiri = (
            getiri / risk
            if risk > 0
            else 0
        )

        # -------------------------------------------------
        # TEKNİK PUAN
        # -------------------------------------------------

        puan = 50
        nedenler = []

        if fiyat > sma20:
            puan += 8
            nedenler.append("Fiyat SMA20 üzerinde")
        else:
            puan -= 8
            nedenler.append("Fiyat SMA20 altında")

        if fiyat > sma50:
            puan += 8
            nedenler.append("Fiyat SMA50 üzerinde")
        else:
            puan -= 8
            nedenler.append("Fiyat SMA50 altında")

        if sma20 > sma50:
            puan += 7
            nedenler.append("SMA20 > SMA50")
        else:
            puan -= 7
            nedenler.append("SMA20 < SMA50")

        if 45 <= rsi_son < 70:
            puan += 8
            nedenler.append("RSI pozitif bölgede")

        elif rsi_son < 30:
            puan += 5
            nedenler.append("RSI aşırı satım bölgesinde")

        elif rsi_son >= 70:
            puan -= 7
            nedenler.append("RSI aşırı alım bölgesinde")

        else:
            nedenler.append("RSI nötr/zayıf")

        if macd_son > signal_son:
            puan += 8
            nedenler.append("MACD sinyal üzerinde")
        else:
            puan -= 8
            nedenler.append("MACD sinyal altında")

        if hist_son > 0:
            puan += 5
            nedenler.append("MACD histogram pozitif")
        else:
            puan -= 5
            nedenler.append("MACD histogram negatif")

        if yukari_kesisim:
            puan += 8
            nedenler.append("MACD yukarı kesişim")

        if asagi_kesisim:
            puan -= 8
            nedenler.append("MACD aşağı kesişim")

        if hacim_orani >= 130:
            puan += 8
            nedenler.append("Hacim güçlü")
        elif hacim_orani >= 100:
            puan += 3
            nedenler.append("Hacim ortalama üstü")
        else:
            puan -= 3
            nedenler.append("Hacim zayıf")

        if gunluk_degisim > 0:
            puan += 3
            nedenler.append("Günlük momentum pozitif")
        elif gunluk_degisim < -3:
            puan -= 3
            nedenler.append("Günlük momentum negatif")

        if risk_getiri >= 2:
            puan += 5
            nedenler.append("Risk/getiri oranı güçlü")

        puan = max(0, min(100, puan))

        return {
            "sembol": sembol,
            "fiyat": fiyat,
            "degisim": gunluk_degisim,
            "yuksek": yuksek,
            "dusuk": dusuk,
            "acilis": acilis,
            "hacim": hacim,
            "hacim20": hacim20,
            "hacim_orani": hacim_orani,
            "sma20": sma20,
            "sma50": sma50,
            "rsi": rsi_son,
            "macd": macd_son,
            "signal": signal_son,
            "hist": hist_son,
            "yukari_kesisim": yukari_kesisim,
            "asagi_kesisim": asagi_kesisim,
            "destek": destek,
            "direnc": direnç,
            "direnc60": direnç60,
            "giris_alt": teknik_giris_alt,
            "giris_ust": teknik_giris_ust,
            "hedef1": hedef1,
            "hedef2": hedef2,
            "stop": stop,
            "risk_getiri": risk_getiri,
            "puan": puan,
            "nedenler": nedenler,
        }

    except Exception:
        return None


# =========================================================
# AGRESİF HİSSE FİLTRESİ
# =========================================================

def agresif_mi(a):

    if not a:
        return False

    puan = 0

    # RSI
    if a["rsi"] < 30:
        puan += 2
    elif a["rsi"] < 40:
        puan += 1

    # MACD
    if a["macd"] > a["signal"]:
        puan += 2

    if a["hist"] > 0:
        puan += 1

    if a["yukari_kesisim"]:
        puan += 3

    # Hacim
    if a["hacim_orani"] >= 150:
        puan += 3
    elif a["hacim_orani"] >= 120:
        puan += 2

    # Trend
    if a["fiyat"] > a["sma20"]:
        puan += 1

    if a["sma20"] > a["sma50"]:
        puan += 1

    # Günlük hareket
    if 0 < a["degisim"] <= 7:
        puan += 1

    # Risk/getiri
    if a["risk_getiri"] >= 2:
        puan += 2

    return puan >= 7


# =========================================================
# YARIN POTANSİYEL PUANI
# =========================================================

def yarin_potansiyel_hesapla(a):

    if not a:
        return -999

    puan = 0

    # Trend
    if a["fiyat"] > a["sma20"]:
        puan += 15

    if a["fiyat"] > a["sma50"]:
        puan += 15

    if a["sma20"] > a["sma50"]:
        puan += 10

    # RSI
    if 45 <= a["rsi"] <= 65:
        puan += 15
    elif 35 <= a["rsi"] < 45:
        puan += 8
    elif a["rsi"] < 30:
        puan += 10
    elif a["rsi"] > 70:
        puan -= 12

    # MACD
    if a["macd"] > a["signal"]:
        puan += 12

    if a["hist"] > 0:
        puan += 8

    if a["yukari_kesisim"]:
        puan += 10

    # Hacim
    if a["hacim_orani"] >= 150:
        puan += 10
    elif a["hacim_orani"] >= 120:
        puan += 7
    elif a["hacim_orani"] >= 100:
        puan += 3

    # Günlük aşırı yükselişi cezalandır
    if a["degisim"] > 7:
        puan -= 12
    elif a["degisim"] > 5:
        puan -= 6

    # Sert düşüşte tepki ihtimali
    if a["degisim"] < -7:
        puan -= 5

    # Dirence çok yakınsa puan düşür
    if a["direnc"] > a["fiyat"]:
        direnç_mesafe = (
            (a["direnc"] - a["fiyat"])
            / a["fiyat"]
        ) * 100

        if direnç_mesafe >= 5:
            puan += 5
        elif direnç_mesafe < 2:
            puan -= 5

    # Risk/getiri
    if a["risk_getiri"] >= 3:
        puan += 8
    elif a["risk_getiri"] >= 2:
        puan += 5

    return max(0, min(100, puan))


# =========================================================
# BIST HİSSELERİNİ GETİR
# =========================================================

def bist_hisseleri_getir():

    try:
        df = bp.companies()

        if df is None or df.empty:
            return []

        if "ticker" in df.columns:
            semboller = df["ticker"].dropna().tolist()
        elif "symbol" in df.columns:
            semboller = df["symbol"].dropna().tolist()
        else:
            return []

        sonuc = []

        for s in semboller:
            s = str(s).strip().upper()

            if s and s.isalnum():
                sonuc.append(s)

        return sorted(list(set(sonuc)))

    except Exception:
        return []


# =========================================================
# TÜM BIST TARAMA
# =========================================================

def bist_tara():

    semboller = bist_hisseleri_getir()

    sonuclar = []
    toplam = len(semboller)

    for i, sembol in enumerate(semboller, 1):

        try:
            analiz = hisse_analiz_hesapla(sembol)

            if analiz:
                sonuclar.append(analiz)

        except Exception:
            pass

    return sonuclar, toplam


# =========================================================
# HİSSE ÖZETİ MESAJI
# =========================================================

def ozet_mesaji(a):

    trend = trend_yorumu(
        a["fiyat"],
        a["sma20"],
        a["sma50"]
    )

    rsi_y = rsi_yorumu(a["rsi"])

    hacim_y = hacim_yorumu(a["hacim_orani"])

    macd_y = macd_yorumu(
        a["macd"],
        a["signal"],
        a["hist"]
    )

    return (
        f"📊 {a['sembol']} DETAYLI HİSSE ÖZETİ\n"
        f"━━━━━━━━━━━━━━\n\n"

        f"💰 Fiyat: {a['fiyat']:.2f} TL\n"
        f"📈 Günlük: {a['degisim']:+.2f}%\n"
        f"🔺 Günlük Yüksek: {a['yuksek']:.2f}\n"
        f"🔻 Günlük Düşük: {a['dusuk']:.2f}\n"
        f"🔵 Açılış: {a['acilis']:.2f}\n"
        f"📦 Hacim: {a['hacim']:,.0f}\n\n"

        f"📊 TEKNİK GÖSTERGELER\n"
        f"RSI(14): {a['rsi']:.2f} — {rsi_y}\n"
        f"SMA20: {a['sma20']:.2f}\n"
        f"SMA50: {a['sma50']:.2f}\n"
        f"Trend: {trend}\n\n"

        f"📉 MACD\n"
        f"MACD: {a['macd']:.4f}\n"
        f"Sinyal: {a['signal']:.4f}\n"
        f"Histogram: {a['hist']:.4f}\n"
        f"{macd_y}\n"
        f"Kesişim: "
        f"{'🟢 YUKARI' if a['yukari_kesisim'] else '🔴 AŞAĞI' if a['asagi_kesisim'] else '⚪ YOK'}\n\n"

        f"📦 HACİM ANALİZİ\n"
        f"20G Ortalama: {a['hacim20']:,.0f}\n"
        f"Hacim Oranı: %{a['hacim_orani']:.1f}\n"
        f"{hacim_y}\n\n"

        f"🧱 DESTEK / DİRENÇ\n"
        f"Destek: {a['destek']:.2f}\n"
        f"Direnç: {a['direnc']:.2f}\n"
        f"Üst Direnç: {a['direnc60']:.2f}\n\n"

        f"🎯 TEKNİK BÖLGELER\n"
        f"Giriş Bölgesi: {a['giris_alt']:.2f} - {a['giris_ust']:.2f}\n"
        f"Hedef 1: {a['hedef1']:.2f}\n"
        f"Hedef 2: {a['hedef2']:.2f}\n"
        f"Stop: {a['stop']:.2f}\n"
        f"Risk/Getiri: {a['risk_getiri']:.2f}\n\n"

        f"⭐ TEKNİK SKOR: {a['puan']}/100\n\n"

        f"🔎 SKOR NEDENLERİ\n"
        + "".join(
            f"• {n}\n"
            for n in a["nedenler"]
        )
        + "\n"
        f"⚠️ Bu çıktı teknik göstergelere dayalı "
        f"algoritmik analizdir; kesin yükseliş/alış garantisi değildir."
    )


# =========================================================
# GELİŞMİŞ SİNYAL MESAJI
# =========================================================

def sinyal_mesaji(a):

    if a["puan"] >= 75:
        sinyal = "🟢 GÜÇLÜ POZİTİF ADAY"

    elif a["puan"] >= 65:
        sinyal = "🟢 POZİTİF ADAY"

    elif a["rsi"] < 30 and a["hist"] > a["hist"]:
        sinyal = "🟠 AŞIRI SATIM / TEPKİ ADAYI"

    elif a["puan"] <= 35:
        sinyal = "🔴 ZAYIF"

    else:
        sinyal = "🟡 NÖTR / BEKLE"

    return (
        f"📡 {a['sembol']} GELİŞMİŞ SİNYAL\n"
        f"━━━━━━━━━━━━━━\n\n"

        f"💰 Fiyat: {a['fiyat']:.2f} TL\n"
        f"📈 Günlük: {a['degisim']:+.2f}%\n\n"

        f"📊 GÖSTERGELER\n"
        f"RSI: {a['rsi']:.2f} — {rsi_yorumu(a['rsi'])}\n"
        f"SMA20: {a['sma20']:.2f}\n"
        f"SMA50: {a['sma50']:.2f}\n"
        f"MACD: {a['macd']:.4f}\n"
        f"Signal: {a['signal']:.4f}\n"
        f"Histogram: {a['hist']:.4f}\n\n"

        f"📦 HACİM\n"
        f"Oran: %{a['hacim_orani']:.1f}\n"
        f"{hacim_yorumu(a['hacim_orani'])}\n\n"

        f"🎯 SİNYAL\n"
        f"{sinyal}\n"
        f"Teknik Skor: {a['puan']}/100\n\n"

        f"🧱 Seviyeler\n"
        f"Destek: {a['destek']:.2f}\n"
        f"Direnç: {a['direnc']:.2f}\n"
        f"Hedef 1: {a['hedef1']:.2f}\n"
        f"Hedef 2: {a['hedef2']:.2f}\n"
        f"Stop: {a['stop']:.2f}\n"
        f"Risk/Getiri: {a['risk_getiri']:.2f}\n\n"

        f"⚠️ Algoritmik teknik analizdir; kesin al/sat sonucu değildir."
    )


# =========================================================
# ANLIK AGRESİFLER
# =========================================================

def agresif_mesaji(sonuclar, toplam):

    agresifler = []

    for a in sonuclar:
        if agresif_mi(a):
            skor = yarin_potansiyel_hesapla(a)
            agresifler.append(
                (skor, a)
            )

    agresifler.sort(
        key=lambda x: x[0],
        reverse=True
    )

    mesaj = (
        "🔥 ANLIK AGRESİF HİSSELER\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🔎 Taranan hisse: {toplam}\n"
        f"🔥 Bulunan agresif aday: {len(agresifler)}\n\n"
    )

    if not agresifler:
        mesaj += (
            "Şu anda kriterleri karşılayan agresif aday bulunamadı.\n"
        )

        return mesaj

    for i, (skor, a) in enumerate(agresifler, 1):

        mesaj += (
            f"{i}. {a['sembol']} — "
            f"Potansiyel {skor}/100\n"
            f"   Fiyat: {a['fiyat']:.2f} TL | "
            f"Günlük: {a['degisim']:+.2f}%\n"
            f"   RSI: {a['rsi']:.1f} | "
            f"Hacim: %{a['hacim_orani']:.0f}\n"
            f"   MACD: "
            f"{'Pozitif' if a['macd'] > a['signal'] else 'Negatif'}\n"
            f"   Destek: {a['destek']:.2f} | "
            f"Direnç: {a['direnc']:.2f}\n"
            f"   Hedef1: {a['hedef1']:.2f} | "
            f"Stop: {a['stop']:.2f}\n\n"
        )

    mesaj += (
        "⚠️ Liste, o anki teknik verilerle oluşturulur. "
        "Adayların yükselmesi garanti değildir."
    )

    return mesaj


# =========================================================
# YARIN TOP 10
# =========================================================

def yarin_top10_mesaji(sonuclar, toplam):

    sirali = []

    for a in sonuclar:

        skor = yarin_potansiyel_hesapla(a)

        if skor >= 55:
            sirali.append(
                (skor, a)
            )

    sirali.sort(
        key=lambda x: x[0],
        reverse=True
    )

    top10 = sirali[:10]

    mesaj = (
        "🏆 YARIN İÇİN TOP 10\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🔎 Taranan hisse: {toplam}\n"
        f"📊 Teknik aday: {len(sirali)}\n\n"
        "Sıralama; trend, RSI, MACD, hacim, "
        "direnç mesafesi ve risk/getiri gibi teknik "
        "kriterlerin birleşiminden oluşturulur.\n\n"
    )

    if not top10:
        mesaj += "❌ Yeterli teknik aday bulunamadı."
        return mesaj

    for i, (skor, a) in enumerate(top10, 1):

        mesaj += (
            f"🏅 {i}. {a['sembol']} — {skor}/100\n"
            f"   💰 {a['fiyat']:.2f} TL "
            f"({a['degisim']:+.2f}%)\n"
            f"   RSI {a['rsi']:.1f} | "
            f"Hacim %{a['hacim_orani']:.0f}\n"
            f"   MACD: "
            f"{'Pozitif' if a['macd'] > a['signal'] else 'Negatif'}\n"
            f"   Destek {a['destek']:.2f} | "
            f"Direnç {a['direnc']:.2f}\n"
            f"   Hedef1 {a['hedef1']:.2f} | "
            f"Stop {a['stop']:.2f}\n\n"
        )

    mesaj += (
        "━━━━━━━━━━━━━━\n"
        "🔥 AYNI TARAMADAN AGRESİF ADAYLAR\n\n"
    )

    agresifler = []

    for a in sonuclar:
        if agresif_mi(a):
            agresifler.append(
                (
                    yarin_potansiyel_hesapla(a),
                    a
                )
            )

    agresifler.sort(
        key=lambda x: x[0],
        reverse=True
    )

    if agresifler:

        for skor, a in agresifler:

            mesaj += (
                f"🔥 {a['sembol']} "
                f"({skor}/100) — "
                f"{a['fiyat']:.2f} TL\n"
                f"   RSI {a['rsi']:.1f}, "
                f"Hacim %{a['hacim_orani']:.0f}, "
                f"MACD "
                f"{'pozitif' if a['macd'] > a['signal'] else 'negatif'}\n"
            )

    else:
        mesaj += "Şu anda agresif kriterleri karşılayan aday yok.\n"

    mesaj += (
        "\n⚠️ Bu sıralama algoritmik teknik potansiyeldir; "
        "ertesi gün yükseliş garantisi veya yatırım tavsiyesi değildir."
    )

    return mesaj


# =========================================================
# START MENÜ
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
                callback_data="agresif"
            )
        ],
        [
            InlineKeyboardButton(
                "🏆 Yarın İçin TOP 10",
                callback_data="top10"
            )
        ],
    ]

    await update.message.reply_text(
        "🤖 BIST AI TERMINAL\n\n"
        "Bir işlem seç:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# BUTONLAR
# =========================================================

async def buton(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    if query.data == "ozet":

        context.user_data["hisse_bekleniyor"] = True
        context.user_data["mod"] = "ozet"

        await query.message.reply_text(
            "📈 HİSSE ÖZETİ\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: GENKM"
        )

    elif query.data == "sinyal":

        context.user_data["hisse_bekleniyor"] = True
        context.user_data["mod"] = "sinyal"

        await query.message.reply_text(
            "📡 GELİŞMİŞ SİNYAL\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: GENKM"
        )

    elif query.data == "agresif":

        await query.message.reply_text(
            "🔥 BIST TARANIYOR...\n\n"
            "Tüm BIST hisseleri teknik olarak "
            "kontrol ediliyor.\n"
            "Bu işlem biraz sürebilir."
        )

        try:

            sonuclar, toplam = bist_tara()

            mesaj = agresif_mesaji(
                sonuclar,
                toplam
            )

            parcalar = mesaj_parcala_gonder(
                update,
                mesaj
            )

            for parca in parcalar:
                await query.message.reply_text(parca)

        except Exception as e:

            await query.message.reply_text(
                f"❌ Tarama hatası:\n{e}"
            )

    elif query.data == "top10":

        await query.message.reply_text(
            "🏆 YARIN İÇİN BIST TARANIYOR...\n\n"
            "Tüm BIST hisseleri teknik olarak "
            "değerlendiriliyor."
        )

        try:

            sonuclar, toplam = bist_tara()

            mesaj = yarin_top10_mesaji(
                sonuclar,
                toplam
            )

            parcalar = mesaj_parcala_gonder(
                update,
                mesaj
            )

            for parca in parcalar:
                await query.message.reply_text(parca)

        except Exception as e:

            await query.message.reply_text(
                f"❌ TOP 10 tarama hatası:\n{e}"
            )


# =========================================================
# HİSSE OKU
# =========================================================

async def hisse_oku(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get(
        "hisse_bekleniyor"
    ):
        return

    sembol = update.message.text.strip().upper()

    mod = context.user_data.get("mod")

    try:

        await update.message.reply_text(
            f"🔎 {sembol} analiz ediliyor..."
        )

        analiz = hisse_analiz_hesapla(
            sembol
        )

        if not analiz:

            await update.message.reply_text(
                "❌ Bu hisse için yeterli veri bulunamadı."
            )

            return

        if mod == "ozet":

            mesaj = ozet_mesaji(
                analiz
            )

        else:

            mesaj = sinyal_mesaji(
                analiz
            )

        parcalar = mesaj_parcala_gonder(
            update,
            mesaj
        )

        for parca in parcalar:

            await update.message.reply_text(
                parca
            )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Analiz hatası:\n{e}"
        )

    finally:

        context.user_data[
            "hisse_bekleniyor"
        ] = False

        context.user_data[
            "mod"
        ] = None


# =========================================================
# UYGULAMA
# =========================================================

if not TOKEN:

    raise RuntimeError(
        "BOT_TOKEN Railway değişkeni bulunamadı."
    )


app = Application.builder().token(TOKEN).build()

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