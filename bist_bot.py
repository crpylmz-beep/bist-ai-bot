import os
import math
import time
import asyncio
import json
from datetime import datetime
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

DATA_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "bist_data.json"
)

TAHMIN_GECMISI_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "tahmin_gecmisi.json"
)


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


def tahmin_gecmisi_oku():
    try:
        if not os.path.exists(TAHMIN_GECMISI_FILE):
            return {"surum": 1, "tahminler": [], "ogrenme_gecmisi": []}

        with open(TAHMIN_GECMISI_FILE, "r", encoding="utf-8") as f:
            veri = json.load(f)

        if not isinstance(veri, dict):
            raise ValueError("Tahmin geçmişi geçersiz formatta")

        veri.setdefault("surum", 1)
        veri.setdefault("tahminler", [])
        veri.setdefault("ogrenme_gecmisi", [])
        return veri

    except Exception as e:
        print("TAHMIN GECMISI OKUMA HATASI:", e)
        return {"surum": 1, "tahminler": [], "ogrenme_gecmisi": []}


def tahmin_gecmisi_yaz(veri):
    try:
        os.makedirs(os.path.dirname(TAHMIN_GECMISI_FILE), exist_ok=True)
        gecici = TAHMIN_GECMISI_FILE + ".tmp"

        with open(gecici, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)

        os.replace(gecici, TAHMIN_GECMISI_FILE)
        return True

    except Exception as e:
        print("TAHMIN GECMISI YAZMA HATASI:", e)
        return False


def rsi_hesapla(close, periyot=14):
    delta = close.diff()

    kazanc = delta.clip(lower=0)
    kayip = -delta.clip(upper=0)

    ort_kazanc = kazanc.rolling(periyot).mean()
    ort_kayip = kayip.rolling(periyot).mean()

    rs = ort_kazanc / ort_kayip.replace(
        0,
        float("nan")
    )

    rsi = 100 - (
        100 / (1 + rs)
    )

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
        kes = mesaj.rfind(
            "\n",
            0,
            limit
        )

        if kes <= 0:
            kes = limit

        parcalar.append(
            mesaj[:kes]
        )

        mesaj = mesaj[kes:].lstrip()

    if mesaj:
        parcalar.append(mesaj)

    return parcalar


# =========================================================
# TEKNİK ANALİZ
# =========================================================

def hisse_analiz_hesapla(
    sembol,
    period="6mo"
):
    try:
        hisse = bp.Ticker(sembol)

        veri = hisse.history(
            period=period
        )

        if veri is None or veri.empty:
            return None

        if len(veri) < 2:
            return None

        close = veri["Close"]
        volume = veri["Volume"]

        son = veri.iloc[-1]
        onceki = veri.iloc[-2]

        fiyat = guvenli_float(
            son["Close"]
        )

        onceki_fiyat = guvenli_float(
            onceki["Close"]
        )

        if fiyat <= 0 or onceki_fiyat <= 0:
            return None

        gunluk_degisim = (
            (fiyat - onceki_fiyat)
            / onceki_fiyat
        ) * 100

        yuksek = guvenli_float(
            son["High"]
        )

        dusuk = guvenli_float(
            son["Low"]
        )

        acilis = guvenli_float(
            son["Open"]
        )

        hacim = guvenli_float(
            son["Volume"]
        )

        sma20 = guvenli_float(
            close.rolling(20).mean().iloc[-1]
        )

        sma50 = guvenli_float(
            close.rolling(50).mean().iloc[-1]
        )

        hacim20 = guvenli_float(
            volume.rolling(20).mean().iloc[-1]
        )

        hacim_orani = (
            (hacim / hacim20) * 100
            if hacim20 > 0
            else 0
        )

        rsi = rsi_hesapla(close)

        rsi_son = guvenli_float(
            rsi.iloc[-1]
        )

        rsi_onceki = guvenli_float(
            rsi.iloc[-2]
        )

        ema12 = close.ewm(
            span=12,
            adjust=False
        ).mean()

        ema26 = close.ewm(
            span=26,
            adjust=False
        ).mean()

        macd = ema12 - ema26

        signal = macd.ewm(
            span=9,
            adjust=False
        ).mean()

        histogram = macd - signal

        macd_son = guvenli_float(
            macd.iloc[-1]
        )

        signal_son = guvenli_float(
            signal.iloc[-1]
        )

        hist_son = guvenli_float(
            histogram.iloc[-1]
        )

        hist_onceki = guvenli_float(
            histogram.iloc[-2]
        )

        macd_onceki = guvenli_float(
            macd.iloc[-2]
        )

        signal_onceki = guvenli_float(
            signal.iloc[-2]
        )

        yukari_kesisim = (
            macd_onceki <= signal_onceki
            and macd_son > signal_son
        )

        asagi_kesisim = (
            macd_onceki >= signal_onceki
            and macd_son < signal_son
        )

        # -------------------------------------------------
        # GÜNLÜK MUM / TEPKİ ÖLÇÜMLERİ
        # -------------------------------------------------

        gunluk_aralik = yuksek - dusuk

        if gunluk_aralik > 0:
            kapanis_pozisyonu = (
                (fiyat - dusuk)
                / gunluk_aralik
            ) * 100
        else:
            kapanis_pozisyonu = 50

        pozitif_mum = fiyat > acilis
        negatif_mum = fiyat < acilis

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

        tr1 = (
            veri["High"]
            - veri["Low"]
        )

        tr2 = (
            veri["High"]
            - onceki_kapanis
        ).abs()

        tr3 = (
            veri["Low"]
            - onceki_kapanis
        ).abs()

        true_range = tr1.combine(
            tr2,
            max
        )

        true_range = true_range.combine(
            tr3,
            max
        )

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
        # YARIN ICIN KISA VADE ISLEM PLANI
        # -------------------------------------------------

        # YARIN ICIN YAKIN DIRENC / HACIMLI KIRILIM
        #
        # Eski sert tepelerin yarinlik kirilim seviyesini
        # gereksiz yere cok yukariya tasimasini engelliyoruz.
        # Son 3 tamamlanmis gunun yuksekleri incelenir.
        if len(veri) >= 4:
            onceki3 = veri.iloc[-4:-1]
        else:
            onceki3 = veri.iloc[:-1]

        yakin_tavan = fiyat + atr14 * 0.80

        yakin_direncler = []

        if len(onceki3) > 0:
            for seviye in onceki3["High"]:
                seviye = guvenli_float(seviye)
                if fiyat < seviye <= yakin_tavan:
                    yakin_direncler.append(seviye)

        # Fiyata yakin gercek bir onceki tepe varsa onu kullan.
        # Yoksa ATR tabanli dinamik kirilim seviyesi olustur.
        if yakin_direncler:
            yarin_kirilim = min(yakin_direncler)
        else:
            yarin_kirilim = fiyat + atr14 * 0.50

        # Yarin icin daha kontrollu dinamik alim bolgesi.
        # ATR kullanilir ancak cok oynak hisselerde bolgenin
        # gereksiz yere genislemesi sinirlandirilir.
        alim_alt_mesafe = min(
            atr14 * 0.23,
            fiyat * 0.022
        )

        alim_ust_mesafe = min(
            atr14 * 0.03,
            fiyat * 0.004
        )

        yarin_alim_alt = max(
            0.01,
            fiyat - alim_alt_mesafe
        )

        yarin_alim_ust = max(
            yarin_alim_alt,
            fiyat + alim_ust_mesafe
        )

        # Ilk kisa vadeli kar alma seviyesi kirilimdan bagimsizdir.
        yarin_kar_al = fiyat + atr14 * 0.50

        # Kisa vadeli stop.
        # ATR ile hesaplanir fakat asiri genis stop engellenir.
        stop_mesafe = min(
            atr14 * 0.50,
            fiyat * 0.046
        )

        yarin_stop = max(
            0.01,
            fiyat - stop_mesafe
        )

        # Kirilim sonrasi ilk teknik hedef
        yarin_kirilim_hedef = yarin_kirilim + atr14 * 0.60

        # HACIMLI KIRILIM DURUMU
        #
        # Yuksek hacim tek basina olumlu kirilim degildir.
        # Fiyat kirilim seviyesinin uzerinde olmali ve
        # gunluk mum da pozitif olmali.
        if (
            fiyat > yarin_kirilim
            and hacim_orani >= 120
            and pozitif_mum
        ):
            hacimli_kirilim_durum = "GERCEKLESTI"

        elif fiyat > yarin_kirilim:
            hacimli_kirilim_durum = "HACIM_ZAYIF"

        else:
            hacimli_kirilim_durum = "BEKLENIYOR"

        # -------------------------------------------------
        # TEKNİK PUAN
        # -------------------------------------------------

        puan = 50

        nedenler = []

        if sma20 > 0:

            if fiyat > sma20:
                puan += 8

                fark_yuzde = ((fiyat - sma20) / sma20) * 100

                nedenler.append(
                    f"Fiyat SMA20 üzerinde: +%{fark_yuzde:.2f}"
                )

            else:
                puan -= 8

                fark_yuzde = ((fiyat - sma20) / sma20) * 100

                nedenler.append(
                    f"Fiyat SMA20 altında: %{fark_yuzde:.2f}"
                )


        if sma50 > 0:

            if fiyat > sma50:
                puan += 8

                fark_yuzde = ((fiyat - sma50) / sma50) * 100

                nedenler.append(
                    f"Fiyat SMA50 üzerinde: +%{fark_yuzde:.2f}"
                )

            else:
                puan -= 8

                fark_yuzde = ((fiyat - sma50) / sma50) * 100

                nedenler.append(
                    f"Fiyat SMA50 altında: %{fark_yuzde:.2f}"
                )


            if sma20 > sma50:
                puan += 7

                fark_yuzde = ((sma20 - sma50) / sma50) * 100

                nedenler.append(
                    f"SMA20 > SMA50: +%{fark_yuzde:.2f}"
                )

            else:
                puan -= 7

                fark_yuzde = ((sma20 - sma50) / sma50) * 100

                nedenler.append(
                    f"SMA20 < SMA50: %{fark_yuzde:.2f}"
                )


        if 45 <= rsi_son < 70:
            puan += 8

            nedenler.append(
                f"RSI pozitif bölgede: {rsi_son:.2f}"
            )

        elif rsi_son < 30:
            puan += 2

            nedenler.append(
                f"RSI aşırı satım bölgesinde: {rsi_son:.2f}"
            )

        elif rsi_son >= 70:
            puan -= 7

            nedenler.append(
                f"RSI aşırı alım bölgesinde: {rsi_son:.2f}"
            )

        else:
            nedenler.append(
                f"RSI nötr/zayıf: {rsi_son:.2f}"
            )


        if macd_son > signal_son:
            puan += 8

            macd_fark = macd_son - signal_son

            nedenler.append(
                f"MACD Signal üzerinde: +{macd_fark:.4f}"
            )

        else:
            puan -= 8

            macd_fark = macd_son - signal_son

            nedenler.append(
                f"MACD Signal altında: {macd_fark:.4f}"
            )


        if hist_son > 0:
            puan += 5

            nedenler.append(
                f"MACD histogram pozitif: +{hist_son:.4f}"
            )

        else:
            puan -= 5

            nedenler.append(
                f"MACD histogram negatif: {hist_son:.4f}"
            )


        if yukari_kesisim:
            puan += 8

            nedenler.append(
                "MACD yukarı kesişim gerçekleşti"
            )


        if asagi_kesisim:
            puan -= 8

            nedenler.append(
                "MACD aşağı kesişim gerçekleşti"
            )


        if hacim_orani >= 130:
            puan += 8

            hacim_fark = hacim_orani - 100

            nedenler.append(
                f"Hacim güçlü: 20 günlük ortalamanın +%{hacim_fark:.1f} üzerinde"
            )

        elif hacim_orani >= 100:
            puan += 3

            hacim_fark = hacim_orani - 100

            nedenler.append(
                f"Hacim ortalama üstü: +%{hacim_fark:.1f}"
            )

        else:
            puan -= 3

            hacim_fark = 100 - hacim_orani

            nedenler.append(
                f"Hacim zayıf: 20 günlük ortalamanın %{hacim_fark:.1f} altında"
            )


        if gunluk_degisim > 0:
            puan += 3

            nedenler.append(
                f"Günlük momentum pozitif: +%{gunluk_degisim:.2f}"
            )

        elif gunluk_degisim < -3:
            puan -= 3

            nedenler.append(
                f"Günlük momentum negatif: %{gunluk_degisim:.2f}"
            )


        if risk_getiri >= 2:
            puan += 5

            nedenler.append(
                f"Risk/getiri oranı güçlü: {risk_getiri:.2f}"
            )

        elif risk_getiri > 0:
            nedenler.append(
                f"Risk/getiri oranı: {risk_getiri:.2f}"
            )


        puan = max(
            0,
            min(100, puan)
        )
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
            "veri_sayisi": len(veri),
            "rsi": rsi_son,
            "rsi_onceki": rsi_onceki,
            "macd": macd_son,
            "signal": signal_son,
            "hist": hist_son,
            "hist_onceki": hist_onceki,
            "yukari_kesisim": yukari_kesisim,
            "asagi_kesisim": asagi_kesisim,
            "pozitif_mum": pozitif_mum,
            "negatif_mum": negatif_mum,
            "kapanis_pozisyonu": kapanis_pozisyonu,
            "destek": destek,
            "direnc": direnç,
            "direnc60": direnç60,
            "giris_alt": teknik_giris_alt,
            "giris_ust": teknik_giris_ust,
            "hedef1": hedef1,
            "hedef2": hedef2,
            "stop": stop,
            "risk_getiri": risk_getiri,
            "atr14": atr14,
            "yarin_alim_alt": yarin_alim_alt,
            "yarin_alim_ust": yarin_alim_ust,
            "yarin_kar_al": yarin_kar_al,
            "yarin_stop": yarin_stop,
            "yarin_kirilim": yarin_kirilim,
            "yarin_kirilim_hedef": yarin_kirilim_hedef,
            "hacimli_kirilim_durum": hacimli_kirilim_durum,
            "puan": puan,
            "nedenler": nedenler,
        }

    except Exception:
        return None


# =========================================================
# SİNYAL MOTORU
# =========================================================

def sinyal_sinifi(a):

    if not a:
        return "NÖTR"

    rsi = guvenli_float(a.get("rsi"))
    rsi_onceki = guvenli_float(a.get("rsi_onceki"))
    hacim = guvenli_float(a.get("hacim_orani"))
    macd = guvenli_float(a.get("macd"))
    signal = guvenli_float(a.get("signal"))
    hist = guvenli_float(a.get("hist"))
    hist_onceki = guvenli_float(a.get("hist_onceki"))
    degisim = guvenli_float(a.get("degisim"))
    fiyat = guvenli_float(a.get("fiyat"))
    sma20 = guvenli_float(a.get("sma20"))
    sma50 = guvenli_float(a.get("sma50"))
    yukari_kesisim = bool(a.get("yukari_kesisim"))
    asagi_kesisim = bool(a.get("asagi_kesisim"))
    pozitif_mum = bool(a.get("pozitif_mum"))
    negatif_mum = bool(a.get("negatif_mum"))
    kapanis_pozisyonu = guvenli_float(a.get("kapanis_pozisyonu"))

    if degisim >= 8 or degisim <= -8:
        return "NÖTR"

    if rsi >= 70:
        return "ASIRI_ALIM"

    if 0 < rsi < 30:
        rsi_toparlaniyor = (rsi - rsi_onceki) >= 0.5
        hist_toparlaniyor = hist > hist_onceki
        temel_tepki = (-7 < degisim < 5 and pozitif_mum and kapanis_pozisyonu >= 35 and hacim >= 70)

        if temel_tepki:
            if degisim >= 0 and (rsi_toparlaniyor or hist_toparlaniyor):
                return "ASIRI_SATIM"
            if degisim < 0 and rsi_toparlaniyor and hist_toparlaniyor:
                return "ASIRI_SATIM"
        return "NÖTR"

    if rsi <= 0:
        return "NÖTR"

    alis_puan = 0
    if degisim > 0 and 35 <= rsi < 68:
        if macd > signal:
            alis_puan += 2
        if hist > 0:
            alis_puan += 2
        if yukari_kesisim:
            alis_puan += 3
        if fiyat > sma20:
            alis_puan += 2
        if sma50 > 0 and sma20 > sma50:
            alis_puan += 2
        if hacim >= 150:
            alis_puan += 2
        elif hacim >= 120:
            alis_puan += 1
        if 0 < degisim < 8:
            alis_puan += 1
        if pozitif_mum:
            alis_puan += 1
    if degisim >= 6:
        alis_puan -= 2
    if alis_puan >= 9:
        return "AGRESIF_ALIS"

    satis_puan = 0
    if degisim < 0 and 32 <= rsi < 68:
        if macd < signal:
            satis_puan += 2
        if hist < 0:
            satis_puan += 2
        if asagi_kesisim:
            satis_puan += 3
        if fiyat < sma20:
            satis_puan += 2
        if sma50 > 0 and sma20 < sma50:
            satis_puan += 2
        if hacim >= 150:
            satis_puan += 2
        elif hacim >= 120:
            satis_puan += 1
        if -8 < degisim < 0:
            satis_puan += 1
        if negatif_mum:
            satis_puan += 1
    if degisim <= -6:
        satis_puan -= 2
    if satis_puan >= 9:
        return "AGRESIF_SATIS"

    return "NÖTR"


def guclu_tepki_mi(a):
    if not a or sinyal_sinifi(a) != "ASIRI_SATIM":
        return False

    rsi = guvenli_float(a.get("rsi"))
    rsi_onceki = guvenli_float(a.get("rsi_onceki"))
    hist = guvenli_float(a.get("hist"))
    hist_onceki = guvenli_float(a.get("hist_onceki"))
    hacim = guvenli_float(a.get("hacim_orani"))
    kapanis = guvenli_float(a.get("kapanis_pozisyonu"))

    return (
        (rsi - rsi_onceki) >= 0.5
        and hist > hist_onceki
        and hacim >= 90
        and kapanis >= 50
    )


def tepki_puani(a):
    if not guclu_tepki_mi(a):
        return -999.0

    rsi_fark = guvenli_float(a.get("rsi")) - guvenli_float(a.get("rsi_onceki"))
    hist_fark = guvenli_float(a.get("hist")) - guvenli_float(a.get("hist_onceki"))
    hacim = guvenli_float(a.get("hacim_orani"))
    kapanis = guvenli_float(a.get("kapanis_pozisyonu"))
    degisim = guvenli_float(a.get("degisim"))
    risk_getiri = guvenli_float(a.get("risk_getiri"))

    puan = 0.0
    puan += min(25, max(0, rsi_fark * 4))
    puan += min(20, max(0, hist_fark * 20))
    puan += min(20, max(0, hacim / 10))
    puan += min(20, max(0, kapanis / 5))

    if 0 <= degisim <= 2:
        puan += 15
    elif 2 < degisim <= 3:
        puan += 10
    elif 3 < degisim <= 4:
        puan += 0
    elif degisim > 4:
        puan -= 10
    else:
        puan += 3

    # Risk/getiri destekleyici kriterdir; uzak dirençler aşırı puan üretmesin.
    if risk_getiri >= 2:
        puan += min(5, risk_getiri)

    return round(puan, 1)


def tepki_top10(sonuclar):
    adaylar = [a for a in sonuclar if guclu_tepki_mi(a)]
    adaylar.sort(
        key=lambda a: (
            tepki_puani(a),
            guvenli_float(a.get("hacim_orani")),
            guvenli_float(a.get("kapanis_pozisyonu")),
        ),
        reverse=True,
    )
    return adaylar[:10]


def agresif_mi(a):
    sinif = sinyal_sinifi(a)

    return sinif in (
        "AGRESIF_ALIS",
        "AGRESIF_SATIS"
    )


# =========================================================
# BIST HİSSELERİNİ GETİR
# =========================================================

def bist_hisseleri_getir():

    try:
        df = bp.companies()

        if df is None or df.empty:
            return []

        if "ticker" in df.columns:

            semboller = (
                df["ticker"]
                .dropna()
                .tolist()
            )

        elif "symbol" in df.columns:

            semboller = (
                df["symbol"]
                .dropna()
                .tolist()
            )

        else:
            return []

        sonuc = []

        for s in semboller:

            s = str(s).strip().upper()

            if s and s.isalnum():
                sonuc.append(s)

        return sorted(
            list(set(sonuc))
        )

    except Exception:
        return []


# =========================================================
# HIZLI ÖN TARAMA
# =========================================================

def hizli_agresif_tarama(semboller):

    from concurrent.futures import (
        ThreadPoolExecutor,
        as_completed
    )

    def tek_hisse_tara(sembol):

        try:
            hisse = bp.Ticker(sembol)

            veri = hisse.history(
                period="1mo"
            )

            if (
                veri is None
                or veri.empty
                or len(veri) < 10
            ):
                return None

            close = veri["Close"]
            volume = veri["Volume"]

            fiyat = guvenli_float(
                close.iloc[-1]
            )

            onceki_fiyat = guvenli_float(
                close.iloc[-2]
            )

            if (
                fiyat <= 0
                or onceki_fiyat <= 0
            ):
                return None

            degisim = (
                (fiyat - onceki_fiyat)
                / onceki_fiyat
            ) * 100

            hacim = guvenli_float(
                volume.iloc[-1]
            )

            hacim20 = guvenli_float(
                volume.tail(20).mean()
            )

            if hacim20 <= 0:
                return None

            hacim_orani = (
                hacim / hacim20
            ) * 100

            sma5 = guvenli_float(
                close.tail(5).mean()
            )

            sma10 = guvenli_float(
                close.tail(10).mean()
            )

            puan = 0

            # HACİM
            if hacim_orani >= 180:
                puan += 4

            elif hacim_orani >= 150:
                puan += 3

            elif hacim_orani >= 120:
                puan += 2

            elif hacim_orani >= 100:
                puan += 1

            # GÜNLÜK HAREKET
            abs_degisim = abs(degisim)

            if 0.5 <= abs_degisim <= 3:
                puan += 3

            elif 3 < abs_degisim <= 6:
                puan += 2

            elif 6 < abs_degisim < 8:
                puan += 1

            # KISA TREND
            if fiyat > sma5:
                puan += 1

            if sma5 > sma10:
                puan += 2

            elif sma5 < sma10:
                puan += 1

            # AŞIRI HAREKET CEZASI
            if abs_degisim >= 8:
                puan -= 2

            if puan >= 4:

                return {
                    "sembol": sembol,
                    "fiyat": fiyat,
                    "degisim": degisim,
                    "hacim_orani": hacim_orani,
                    "hizli_puan": puan
                }

            return None

        except Exception:
            return None

    adaylar = []
    tamamlanan = 0
    max_workers = 6

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {
            executor.submit(
                tek_hisse_tara,
                sembol
            ): sembol
            for sembol in semboller
        }

        for future in as_completed(futures):

            try:
                sonuc = future.result()

            except Exception:
                sonuc = None

            tamamlanan += 1

            if sonuc:
                adaylar.append(
                    sonuc
                )

            if tamamlanan % 50 == 0:

                print(
                    f"Hızlı tarama: "
                    f"{tamamlanan}/{len(semboller)}"
                )

    adaylar.sort(
        key=lambda x: (
            x["hizli_puan"],
            x["hacim_orani"],
            -abs(x["degisim"])
        ),
        reverse=True
    )

    return adaylar


# =========================================================
# WEB VERİ KAYDI
# =========================================================

def web_verisi_kaydet(sonuclar):

    try:

        web_hisseler = []

        for hisse in sonuclar:

            if not hisse:
                continue

            veri = dict(hisse)

            # Sinyal sınıfını web uygulaması için kaydet
            veri["sinyal"] = sinyal_sinifi(veri)
            veri["guclu_tepki"] = guclu_tepki_mi(veri)
            veri["tepki_puani"] = tepki_puani(veri) if veri["guclu_tepki"] else 0

            web_hisseler.append(veri)

        # BIST 100 verisini al
        xu100 = None

        try:
            endeks = bp.Index("XU100")
            xu100 = endeks.info
        except Exception as e:
            print("BIST 100 VERİ HATASI:", e)

        veri = {
            "guncelleme": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

            "bist100": {
                "fiyat": guvenli_float(
                    xu100.get("last")
                ) if xu100 else None,

                "degisim": guvenli_float(
                    xu100.get("change_percent")
                ) if xu100 else None,

                "acilis": guvenli_float(
                    xu100.get("open")
                ) if xu100 else None,

                "yuksek": guvenli_float(
                    xu100.get("high")
                ) if xu100 else None,

                "dusuk": guvenli_float(
                    xu100.get("low")
                ) if xu100 else None,

                "hacim": guvenli_float(
                    xu100.get("volume")
                ) if xu100 else None
            },

            "hisseler": web_hisseler
        }

        os.makedirs(
            os.path.dirname(DATA_FILE),
            exist_ok=True
        )

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                veri,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )

    except Exception as e:

        print(
            "WEB VERİ KAYIT HATASI:",
            e
        )
def tahmin_sonrasi_fiyatlarini_bul(sembol, tahmin_tarihi, veri_cache=None):
    try:
        if veri_cache is not None and sembol in veri_cache:
            veri = veri_cache[sembol]
        else:
            hisse = bp.Ticker(sembol)
            veri = hisse.history(period="6mo")
            if veri_cache is not None:
                veri_cache[sembol] = veri

        if veri is None or veri.empty:
            return None

        if "Close" not in veri.columns:
            return None

        veri = veri.dropna(subset=["Close"]).copy()

        hedef_tarih = datetime.strptime(
            tahmin_tarihi[:10],
            "%Y-%m-%d"
        ).date()

        tarihler = []
        for tarih in veri.index:
            try:
                if hasattr(tarih, "date"):
                    gun = tarih.date()
                else:
                    gun = datetime.strptime(
                        str(tarih)[:10],
                        "%Y-%m-%d"
                    ).date()
                tarihler.append((gun, tarih))
            except Exception:
                continue

        tarihler.sort(key=lambda x: x[0])

        baslangic = None
        for i, (gun, _) in enumerate(tarihler):
            if gun >= hedef_tarih:
                baslangic = i
                break

        if baslangic is None:
            return None

        sonuc = {}
        vadeler = {
            "1g": 1,
            "3g": 3,
            "5g": 5,
            "10g": 10,
            "20g": 20,
            "60g": 60
        }

        baslangic_fiyat = guvenli_float(
            veri.loc[tarihler[baslangic][1], "Close"]
        )

        if baslangic_fiyat <= 0:
            return None

        for alan, adim in vadeler.items():
            hedef_index = baslangic + adim

            if hedef_index >= len(tarihler):
                sonuc[alan] = None
                continue

            hedef_kayit = tarihler[hedef_index][1]
            hedef_fiyat = guvenli_float(
                veri.loc[hedef_kayit, "Close"]
            )

            sonuc[alan] = {
                "tarih": tarihler[hedef_index][0].isoformat(),
                "fiyat": hedef_fiyat,
                "getiri_yuzde": (
                    ((hedef_fiyat - baslangic_fiyat) / baslangic_fiyat) * 100
                    if hedef_fiyat > 0 else None
                )
            }

        sonuc["baslangic_tarihi"] = tarihler[baslangic][0].isoformat()
        sonuc["baslangic_fiyati"] = baslangic_fiyat
        return sonuc

    except Exception as e:
        print(f"TAHMIN SONUCU VERI HATASI {sembol}:", e)
        return None


def tahmin_sonuclarini_guncelle():
    try:
        veri = tahmin_gecmisi_oku()
        tahminler = veri.get("tahminler", [])

        if not tahminler:
            print("TAHMIN SONUCLARI: Guncellenecek kayit yok")
            return True

        guncellenen = 0
        veri_cache = {}

        for kayit in tahminler:
            if not kayit.get("sembol") or not kayit.get("tarih"):
                continue

            sonuclar = tahmin_sonrasi_fiyatlarini_bul(
                kayit["sembol"],
                kayit["tarih"],
                veri_cache
            )

            if not sonuclar:
                continue

            degisti = False

            for vade in ["1g", "3g", "5g", "10g", "20g", "60g"]:
                alan = "sonuc_" + vade
                yeni_sonuc = sonuclar.get(vade)

                if yeni_sonuc is not None and kayit.get(alan) != yeni_sonuc:
                    kayit[alan] = yeni_sonuc
                    degisti = True

            if degisti:
                guncellenen += 1

        veri["son_guncelleme"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tahmin_gecmisi_yaz(veri)

        print(f"TAHMIN SONUCLARI: {guncellenen} kayit guncellendi")
        return True

    except Exception as e:
        print("TAHMIN SONUCLARI GUNCELLEME HATASI:", e)
        return False


def yarin_top10_listesi(sonuclar):
    sirali = []
    for a in sonuclar:
        skor = yarin_potansiyel_hesapla(a)
        if skor >= 55:
            sirali.append((skor, a))
    sirali.sort(
        key=lambda x: (
            x[0],
            guvenli_float(x[1].get("hacim_orani")),
            guvenli_float(x[1].get("risk_getiri"))
        ),
        reverse=True
    )
    return sirali[:10]


def tahminleri_kaydet(sonuclar, toplam_hisse):
    try:
        veri = tahmin_gecmisi_oku()
        simdi = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tahminler = veri.setdefault("tahminler", [])

        yarin_top10 = yarin_top10_listesi(sonuclar)
        yarin_top10_map = {
            a.get("sembol"): {"sira": i + 1, "puan": skor}
            for i, (skor, a) in enumerate(yarin_top10)
        }

        tepki_top10_liste = tepki_top10(sonuclar)
        tepki_top10_map = {
            a.get("sembol"): {"sira": i + 1, "puan": tepki_puani(a)}
            for i, a in enumerate(tepki_top10_liste)
        }

        eklenen = 0

        for a in sonuclar:
            if not a or not a.get("sembol"):
                continue

            sinyal = sinyal_sinifi(a)
            guclu_tepki = guclu_tepki_mi(a)

            sembol = a.get("sembol")
            yarin_top10_bilgi = yarin_top10_map.get(sembol)
            tepki_top10_bilgi = tepki_top10_map.get(sembol)

            if sinyal == "NÖTR" and not guclu_tepki and not yarin_top10_bilgi and not tepki_top10_bilgi:
                continue

            bugun = simdi[:10]
            tekrar_var = any(
                str(k.get("tarih", ""))[:10] == bugun
                and k.get("sembol") == a.get("sembol")
                and k.get("sinyal") == sinyal
                and bool(k.get("guclu_tepki", False)) == guclu_tepki
                for k in tahminler
            )

            if tekrar_var:
                continue

            kayit = {
                "id": f"{simdi}_{a.get('sembol')}",
                "tarih": simdi,
                "sembol": a.get("sembol"),
                "sinyal": sinyal,
                "guclu_tepki": guclu_tepki,
                "tepki_puani": tepki_puani(a) if guclu_tepki else 0,
                "yarin_top10": bool(yarin_top10_bilgi),
                "yarin_top10_sira": yarin_top10_bilgi.get("sira") if yarin_top10_bilgi else None,
                "yarin_top10_puani": yarin_top10_bilgi.get("puan") if yarin_top10_bilgi else None,
                "tepki_top10": bool(tepki_top10_bilgi),
                "tepki_top10_sira": tepki_top10_bilgi.get("sira") if tepki_top10_bilgi else None,
                "tepki_top10_puani": tepki_top10_bilgi.get("puan") if tepki_top10_bilgi else None,
                "puan": guvenli_float(a.get("puan")),
                "fiyat": guvenli_float(a.get("fiyat")),
                "degisim": guvenli_float(a.get("degisim")),
                "rsi": guvenli_float(a.get("rsi")),
                "rsi_onceki": guvenli_float(a.get("rsi_onceki")),
                "macd": guvenli_float(a.get("macd")),
                "signal": guvenli_float(a.get("signal")),
                "hist": guvenli_float(a.get("hist")),
                "hist_onceki": guvenli_float(a.get("hist_onceki")),
                "hacim_orani": guvenli_float(a.get("hacim_orani")),
                "sma20": guvenli_float(a.get("sma20")),
                "sma50": guvenli_float(a.get("sma50")),
                "yukari_kesisim": bool(a.get("yukari_kesisim")),
                "asagi_kesisim": bool(a.get("asagi_kesisim")),
                "pozitif_mum": bool(a.get("pozitif_mum")),
                "negatif_mum": bool(a.get("negatif_mum")),
                "kapanis_pozisyonu": guvenli_float(a.get("kapanis_pozisyonu")),
                "destek": guvenli_float(a.get("destek")),
                "direnc": guvenli_float(a.get("direnc")),
                "hedef1": guvenli_float(a.get("hedef1")),
                "hedef2": guvenli_float(a.get("hedef2")),
                "stop": guvenli_float(a.get("stop")),
                "risk_getiri": guvenli_float(a.get("risk_getiri")),
                "nedenler": list(a.get("nedenler", [])),
                "toplam_hisse": toplam_hisse,
                "sonuc_1g": None,
                "sonuc_3g": None,
                "sonuc_5g": None,
                "sonuc_10g": None,
                "sonuc_20g": None,
                "sonuc_60g": None,
                "degerlendirme": None
            }

            tahminler.append(kayit)
            eklenen += 1

        veri["son_guncelleme"] = simdi
        tahmin_gecmisi_yaz(veri)
        print(f"TAHMIN HAFIZASI: {eklenen} anlamli sinyal kaydi eklendi")
        return True

    except Exception as e:
        print("TAHMIN KAYIT HATASI:", e)
        return False


def bist_tara():

    try:
        tahmin_sonuclarini_guncelle()
    except Exception as e:
        print("TAHMIN SONUCLARI OTOMATIK GUNCELLEME HATASI:", e)

    semboller = bist_hisseleri_getir()

    toplam = len(semboller)

    sonuclar = []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def analiz_et(sembol):

        try:

            return hisse_analiz_hesapla(
                sembol,
                period="6mo"
            )

        except Exception:

            return None

    tamamlanan = 0

    max_workers = 8

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {
            executor.submit(
                analiz_et,
                sembol
            ): sembol
            for sembol in semboller
        }

        for future in as_completed(futures):

            tamamlanan += 1

            try:

                analiz = future.result()

                if analiz:
                    sonuclar.append(
                        analiz
                    )

            except Exception:
                pass

            if tamamlanan % 25 == 0:
                print(
                    f"ANALİZ: {tamamlanan}/{toplam}"
                )

    web_verisi_kaydet(
        sonuclar
    )

    tahminleri_kaydet(
        sonuclar,
        toplam
    )

    return (
        sonuclar,
        toplam
    )


# =========================================================
# ÖZET MESAJI
# =========================================================

def ozet_mesaji(a):

    trend = trend_yorumu(
        a["fiyat"],
        a["sma20"],
        a["sma50"]
    )

    rsi_y = rsi_yorumu(
        a["rsi"]
    )

    hacim_y = hacim_yorumu(
        a["hacim_orani"]
    )

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

    sinif = sinyal_sinifi(a)

    if sinif == "AGRESIF_ALIS":
        sinyal = "🟢 AGRESİF ALIŞ"

    elif sinif == "AGRESIF_SATIS":
        sinyal = "🔴 AGRESİF SATIŞ"

    elif sinif == "ASIRI_SATIM":
        sinyal = "🟠 AŞIRI SATIM / TEPKİ"

    elif sinif == "ASIRI_ALIM":
        sinyal = "🔵 AŞIRI ALIM"

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

        f"⚠️ Algoritmik teknik analizdir; "
        f"kesin al/sat sonucu değildir."
    )


# =========================================================
# ANLIK AGRESİFLER
# =========================================================

def agresif_mesaji(
    sonuclar,
    toplam
):

    agresif_alis = []
    agresif_satis = []

    for a in sonuclar:

        sinif = sinyal_sinifi(a)

        if sinif == "AGRESIF_ALIS":

            skor = yarin_potansiyel_hesapla(
                a
            )

            agresif_alis.append(
                (skor, a)
            )

        elif sinif == "AGRESIF_SATIS":

            skor = yarin_potansiyel_hesapla(
                a
            )

            agresif_satis.append(
                (skor, a)
            )

    agresif_alis.sort(
        key=lambda x: x[0],
        reverse=True
    )

    agresif_satis.sort(
        key=lambda x: x[0],
        reverse=True
    )

    mesaj = (
        "🔥 AGRESİF HİSSELER\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔎 Taranan hisse: {toplam}\n"
        f"🟢 Agresif Alış: {len(agresif_alis)}\n"
        f"🔴 Agresif Satış: {len(agresif_satis)}\n\n"
    )

    mesaj += (
        "🟢 AGRESİF ALIŞ\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    if agresif_alis:

        for i, (skor, a) in enumerate(
            agresif_alis,
            1
        ):

            mesaj += (
                f"{i}. {a['sembol']} — "
                f"Potansiyel {skor}/100\n"

                f"   💰 {a['fiyat']:.2f} TL | "
                f"Günlük {a['degisim']:+.2f}%\n"

                f"   RSI {a['rsi']:.1f} | "
                f"Hacim %{a['hacim_orani']:.0f}\n"

                f"   MACD: Pozitif\n"

                f"   Destek {a['destek']:.2f} | "
                f"Direnç {a['direnc']:.2f}\n"

                f"   🎯 Hedef1 {a['hedef1']:.2f} | "
                f"Stop {a['stop']:.2f}\n\n"
            )

    else:
        mesaj += (
            "   Aday bulunamadı.\n\n"
        )

    mesaj += (
        "🔴 AGRESİF SATIŞ\n"
        "━━━━━━━━━━━━━━\n\n"
    )

    if agresif_satis:

        for i, (skor, a) in enumerate(
            agresif_satis,
            1
        ):

            mesaj += (
                f"{i}. {a['sembol']} — "
                f"Teknik skor {a['puan']}/100\n"

                f"   💰 {a['fiyat']:.2f} TL | "
                f"Günlük {a['degisim']:+.2f}%\n"

                f"   RSI {a['rsi']:.1f} | "
                f"Hacim %{a['hacim_orani']:.0f}\n"

                f"   MACD: Negatif\n"

                f"   Destek {a['destek']:.2f} | "
                f"Direnç {a['direnc']:.2f}\n"

                f"   ⚠️ Aşağı yönlü momentum\n\n"
            )

    else:
        mesaj += (
            "   Aday bulunamadı.\n\n"
        )

    mesaj += (
        "━━━━━━━━━━━━━━\n"

        "🟢 Agresif Alış ile "
        "🔴 Agresif Satış "
        "birbirinden ayrı değerlendirilir.\n\n"

        "🟠 Aşırı Satım ile "
        "🟢 Agresif Alış aynı sinyal değildir.\n\n"

        "🔵 Aşırı Alım ile "
        "🔴 Agresif Satış aynı sinyal değildir.\n\n"

        "⚠️ Liste anlık teknik göstergelerden oluşturulur; "
        "kesin sonuç veya yatırım tavsiyesi değildir."
    )

    return mesaj


# =========================================================
# YARIN POTANSİYEL HESAPLAMA
# =========================================================

def yarin_potansiyel_hesapla(a):

    if not a:
        return -999

    degisim = guvenli_float(
        a.get("degisim")
    )

    rsi = guvenli_float(
        a.get("rsi")
    )

    fiyat = guvenli_float(
        a.get("fiyat")
    )

    sma20 = guvenli_float(
        a.get("sma20")
    )

    sma50 = guvenli_float(
        a.get("sma50")
    )

    macd = guvenli_float(
        a.get("macd")
    )

    signal = guvenli_float(
        a.get("signal")
    )

    hist = guvenli_float(
        a.get("hist")
    )

    hacim = guvenli_float(
        a.get("hacim_orani")
    )

    risk_getiri = guvenli_float(
        a.get("risk_getiri")
    )

    # SERT FİLTRELER

    if degisim <= -6:
        return -999

    if degisim >= 8:
        return -999

    if rsi < 30:
        return -999

    if rsi >= 70:
        return -999

    puan = 0

    # TREND

    if fiyat > sma20:
        puan += 18

    if sma50 > 0:

        if fiyat > sma50:
            puan += 12

        if sma20 > sma50:
            puan += 10

    # RSI

    if 45 <= rsi <= 62:
        puan += 15

    elif 38 <= rsi < 45:
        puan += 8

    elif 62 < rsi < 68:
        puan += 7

    elif 30 <= rsi < 38:
        puan += 2

    # MACD

    if macd > signal:
        puan += 12

    if hist > 0:
        puan += 8

    if a.get("yukari_kesisim"):
        puan += 8

    # HACİM

    if hacim >= 150:
        puan += 8

    elif hacim >= 120:
        puan += 6

    elif hacim >= 100:
        puan += 3

    # GÜNLÜK MOMENTUM

    if 0 < degisim <= 3:
        puan += 7

    elif 3 < degisim <= 5:
        puan += 5

    elif 5 < degisim < 8:
        puan += 1

    elif -2 < degisim <= 0:
        puan += 1

    # DİRENÇ MESAFESİ

    direnç = guvenli_float(
        a.get("direnc")
    )

    if direnç > fiyat > 0:

        direnç_mesafe = (
            (direnç - fiyat)
            / fiyat
        ) * 100

        if 5 <= direnç_mesafe <= 30:
            puan += 6

        elif 2 <= direnç_mesafe < 5:
            puan += 2

        elif direnç_mesafe > 30:
            puan += 1

    # RİSK / GETİRİ

    if risk_getiri >= 3:
        puan += 6

    elif risk_getiri >= 2:
        puan += 4

    return max(
        0,
        min(100, puan)
    )


# =========================================================
# YARIN TOP 10
# =========================================================

def yarin_top10_mesaji(
    sonuclar,
    toplam
):

    sirali = []

    for a in sonuclar:

        skor = yarin_potansiyel_hesapla(
            a
        )

        if skor >= 55:

            sirali.append(
                (skor, a)
            )

    sirali.sort(
        key=lambda x: (
            x[0],
            x[1].get("hacim_orani", 0),
            x[1].get("risk_getiri", 0)
        ),
        reverse=True
    )

    top10 = sirali[:10]

    mesaj = (
        "🏆 YARIN İÇİN TOP 10\n"
        "━━━━━━━━━━━━━━\n\n"

        f"🔎 Taranan hisse: {toplam}\n"
        f"📊 Teknik aday: {len(sirali)}\n\n"

        "TOP 10 seçiminde aşırı günlük hareketler, "
        "aşırı satım ve aşırı alım bölgeleri ayrıca filtrelenir.\n\n"
    )

    if not top10:

        mesaj += (
            "❌ Yeterli teknik aday bulunamadı."
        )

        return mesaj

    for i, (skor, a) in enumerate(
        top10,
        1
    ):

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

        "📌 Sinyal grupları birbirinden ayrı değerlendirilir:\n\n"

        "🟢 Agresif Alış\n"
        "🔴 Agresif Satış\n"
        "🟠 Aşırı Satım / Tepki\n"
        "🔵 Aşırı Alım\n\n"

        "⚠️ Bu sıralama algoritmik teknik potansiyeldir; "
        "ertesi gün yükseliş garantisi veya yatırım tavsiyesi değildir."
    )

    return mesaj


# =========================================================
# START MENÜ
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
                "🟢 Agresif Alış",
                callback_data="agresif_alis"
            ),

            InlineKeyboardButton(
                "🔴 Agresif Satış",
                callback_data="agresif_satis"
            )
        ],

        [
            InlineKeyboardButton(
                "🟠 Aşırı Satım / Tepki",
                callback_data="asiri_satim"
            ),

            InlineKeyboardButton(
                "🔵 Aşırı Alım",
                callback_data="asiri_alim"
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
            "📈 HİSSE ÖZETİ\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: GENKM"
        )

    elif query.data == "sinyal":

        context.user_data[
            "hisse_bekleniyor"
        ] = True

        context.user_data[
            "mod"
        ] = "sinyal"

        await query.message.reply_text(
            "📡 GELİŞMİŞ SİNYAL\n\n"
            "Hisse kodunu yazın.\n"
            "Örnek: GENKM"
        )

    elif query.data in (
        "agresif_alis",
        "agresif_satis",
        "asiri_satim",
        "asiri_alim"
    ):

        await query.message.reply_text(
            "🔥 BIST TARANIYOR...\n\n"
            "Teknik göstergeler kontrol ediliyor.\n"
            "Bu işlem biraz sürebilir."
        )

        try:

            sonuclar, toplam = await asyncio.to_thread(
                bist_tara
            )

            if query.data == "agresif_alis":

                liste = [
                    a
                    for a in sonuclar
                    if sinyal_sinifi(a)
                    == "AGRESIF_ALIS"
                ]

                baslik = "🟢 AGRESİF ALIŞ"

            elif query.data == "agresif_satis":

                liste = [
                    a
                    for a in sonuclar
                    if sinyal_sinifi(a)
                    == "AGRESIF_SATIS"
                ]

                baslik = "🔴 AGRESİF SATIŞ"

            elif query.data == "asiri_satim":

                liste = [
                    a
                    for a in sonuclar
                    if sinyal_sinifi(a)
                    == "ASIRI_SATIM"
                ]

                baslik = (
                    "🟠 AŞIRI SATIM / TEPKİ"
                )

            else:

                liste = [
                    a
                    for a in sonuclar
                    if sinyal_sinifi(a)
                    == "ASIRI_ALIM"
                ]

                baslik = "🔵 AŞIRI ALIM"

            liste.sort(
                key=lambda a:
                yarin_potansiyel_hesapla(a),
                reverse=True
            )

            mesaj = (
                f"{baslik}\n"
                "━━━━━━━━━━━━━━\n\n"

                f"🔎 Taranan hisse: {toplam}\n"
                f"📊 Bulunan aday: {len(liste)}\n\n"
            )

            if not liste:

                mesaj += (
                    "Aday bulunamadı."
                )

            else:

                for i, a in enumerate(
                    liste,
                    1
                ):

                    mesaj += (
                        f"{i}. {a['sembol']} "
                        f"— {a['fiyat']:.2f} TL\n"

                        f"   📈 Günlük: "
                        f"{a['degisim']:+.2f}%\n"

                        f"   RSI: {a['rsi']:.1f}\n"

                        f"   Hacim: "
                        f"%{a['hacim_orani']:.0f}\n"

                        f"   Destek: "
                        f"{a['destek']:.2f}\n"

                        f"   Direnç: "
                        f"{a['direnc']:.2f}\n"

                        f"   🎯 Hedef1: "
                        f"{a['hedef1']:.2f}\n\n"
                    )

            parcalar = mesaj_parcala_gonder(
                update,
                mesaj
            )

            for parca in parcalar:

                await query.message.reply_text(
                    parca
                )

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

            sonuclar, toplam = await asyncio.to_thread(
                bist_tara
            )

            mesaj = yarin_top10_mesaji(
                sonuclar,
                toplam
            )

            parcalar = mesaj_parcala_gonder(
                update,
                mesaj
            )

            for parca in parcalar:

                await query.message.reply_text(
                    parca
                )

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

    sembol = (
        update.message.text
        .strip()
        .upper()
    )

    mod = context.user_data.get(
        "mod"
    )

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

if TOKEN:

    app = Application.builder().token(
        TOKEN
    ).build()

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

else:

    app = None


# =========================================================
# PROGRAMI ÇALIŞTIR
# =========================================================

if __name__ == "__main__":

    if not TOKEN:
        print("BOT_TOKEN bulunamadı. Telegram botu çalıştırılmadan devam ediliyor.")
    else:
        print("BIST AI Terminal çalışıyor...")
        app.run_polling()
