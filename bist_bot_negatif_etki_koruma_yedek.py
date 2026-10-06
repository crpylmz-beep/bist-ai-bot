import haber_zeka
import haber_etki_motoru
import os
import math
import time
import asyncio
import json
from datetime import datetime
import borsapy as bp
import pandas as pd

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

YARIN_TOP10_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "yarin_top10.json"
)

GUN_ICI_GECERSIZ_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "gun_ici_gecersiz_semboller.json"
)


# =========================================================
# YARDIMCI FONKSİYONLAR
# =========================================================
def gun_ici_gecersiz_oku():
    try:
        if not os.path.exists(GUN_ICI_GECERSIZ_FILE):
            return set()
        with open(GUN_ICI_GECERSIZ_FILE, "r", encoding="utf-8") as f:
            veri = json.load(f)
        return set(veri.get("gecersiz_semboller", []))
    except Exception:
        return set()


def gun_ici_gecersiz_yaz(semboller):
    try:
        os.makedirs(os.path.dirname(GUN_ICI_GECERSIZ_FILE), exist_ok=True)
        veri = {
            "guncelleme": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "gecersiz_semboller": sorted(set(semboller))
        }
        with open(GUN_ICI_GECERSIZ_FILE, "w", encoding="utf-8") as f:
            json.dump(veri, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Gecersiz sembol onbellegi yazilamadi:", e)



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



# =========================================================
# CANLI MAKRO / SEKTOR ETKI OKUYUCU
# =========================================================

_MAKRO_CACHE = {
    "mtime": None,
    "veri": {}
}


def canli_makro_puani_getir(sembol):
    """
    makro_canli_etki.json dosyasini mtime cache ile okur.
    Her hisse analizinde diski tekrar tekrar okumaz.
    """
    try:
        dosya = os.path.join(
            "webapp",
            "data",
            "makro_canli_etki.json"
        )

        if not os.path.exists(dosya):
            return {
                "makro_puani": 0.0,
                "sektor_puani": 0.0,
                "sektor": ""
            }

        mtime = os.path.getmtime(dosya)

        if _MAKRO_CACHE["mtime"] != mtime:
            with open(
                dosya,
                "r",
                encoding="utf-8"
            ) as f:
                _MAKRO_CACHE["veri"] = json.load(f)

            _MAKRO_CACHE["mtime"] = mtime

        hisseler = _MAKRO_CACHE[
            "veri"
        ].get(
            "hisseler",
            {}
        )

        bilgi = hisseler.get(
            str(sembol or "").strip().upper(),
            {}
        )

        return {
            "makro_puani": guvenli_float(
                bilgi.get("makro_puani")
            ),
            "sektor_puani": guvenli_float(
                bilgi.get("sektor_puani")
            ),
            "sektor": str(
                bilgi.get("sektor", "")
            )
        }

    except Exception:
        return {
            "makro_puani": 0.0,
            "sektor_puani": 0.0,
            "sektor": ""
        }


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

        # -------------------------------------------------
        # 20 GUNLUK HACIM AGIRLIKLI REFERANS VWAP
        # -------------------------------------------------
        # Bu deger gunluk OHLCV verisinden hesaplanan
        # referans VWAP'tir. Gercek seans VWAP'i degildir.
        # Dakikalik veri geldiginde seans VWAP'i ayrica
        # hesaplanacaktir.
        typical_price = (
            veri["High"]
            + veri["Low"]
            + veri["Close"]
        ) / 3

        vwap_pv_20 = (
            typical_price * volume
        ).rolling(20).sum()

        vwap_vol_20 = (
            volume
        ).rolling(20).sum()

        vwap20_seri = (
            vwap_pv_20
            / vwap_vol_20.replace(0, float("nan"))
        )

        vwap20 = guvenli_float(
            vwap20_seri.iloc[-1]
        )

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

        vwap20_uzaklik = (
            ((fiyat - vwap20) / vwap20) * 100
            if vwap20 > 0
            else 0
        )

        if vwap20 <= 0:
            vwap20_durum = "VERI_YOK"
        elif fiyat > vwap20:
            vwap20_durum = "USTUNDE"
        elif fiyat < vwap20:
            vwap20_durum = "ALTINDA"
        else:
            vwap20_durum = "ESIT"

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

        # -------------------------------------------------
        # BOLLINGER BANTLARI (20, 2)
        # -------------------------------------------------
        boll_orta_seri = close.rolling(20).mean()
        boll_std_seri = close.rolling(20).std()

        boll_ust_seri = (
            boll_orta_seri
            + 2 * boll_std_seri
        )

        boll_alt_seri = (
            boll_orta_seri
            - 2 * boll_std_seri
        )

        boll_orta = guvenli_float(
            boll_orta_seri.iloc[-1]
        )

        boll_ust = guvenli_float(
            boll_ust_seri.iloc[-1]
        )

        boll_alt = guvenli_float(
            boll_alt_seri.iloc[-1]
        )

        boll_genislik = (
            ((boll_ust - boll_alt) / boll_orta) * 100
            if boll_orta > 0
            else 0
        )

        boll_konum = (
            ((fiyat - boll_alt) / (boll_ust - boll_alt)) * 100
            if boll_ust > boll_alt
            else 50
        )

        if fiyat > boll_ust:
            boll_durum = "UST_BANT_USTU"
        elif fiyat < boll_alt:
            boll_durum = "ALT_BANT_ALTI"
        elif boll_konum >= 80:
            boll_durum = "UST_BANDA_YAKIN"
        elif boll_konum <= 20:
            boll_durum = "ALT_BANDA_YAKIN"
        else:
            boll_durum = "BANT_ICINDE"

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

        # Yarin icin dinamik satim bolgesi.
        # ATR ve yakin teknik direnc birlikte dikkate alinir.
        yarin_satim_alt = max(
            yarin_kar_al,
            fiyat + atr14 * 0.40
        )

        yarin_satim_ust = max(
            yarin_satim_alt,
            min(
                yarin_kirilim,
                fiyat + atr14 * 0.80
            )
        )

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

        # -------------------------------------------------
        # MADDE 7 - KARAR VE GUVEN MOTORU
        # -------------------------------------------------
        al_puani = 0
        sat_puani = 0
        karar_nedenleri = []

        # TREND
        if sma20 > 0 and fiyat > sma20:
            al_puani += 12
            karar_nedenleri.append("Fiyat SMA20 uzerinde")
        elif sma20 > 0 and fiyat < sma20:
            sat_puani += 12

        if sma50 > 0 and sma20 > sma50:
            al_puani += 10
            karar_nedenleri.append("SMA20 SMA50 uzerinde")
        elif sma50 > 0 and sma20 < sma50:
            sat_puani += 10

        # RSI
        if 45 <= rsi_son <= 62:
            al_puani += 12
            karar_nedenleri.append("RSI pozitif bolgede")
        elif rsi_son >= 70:
            sat_puani += 12
        elif rsi_son < 30:
            sat_puani += 5

        # MACD
        if macd_son > signal_son:
            al_puani += 12
            karar_nedenleri.append("MACD Signal uzerinde")
        elif macd_son < signal_son:
            sat_puani += 12

        if hist_son > 0:
            al_puani += 8
            karar_nedenleri.append("MACD histogram pozitif")
        elif hist_son < 0:
            sat_puani += 8

        if yukari_kesisim:
            al_puani += 8
            karar_nedenleri.append("MACD yukari kesisim")
        elif asagi_kesisim:
            sat_puani += 8

        # HACIM
        if hacim_orani >= 150:
            al_puani += 10
            karar_nedenleri.append("Guclu hacim")
        elif hacim_orani >= 120:
            al_puani += 7
        elif 0 < hacim_orani < 70:
            sat_puani += 7

        # VWAP
        if vwap20_durum == "USTUNDE":
            al_puani += 10
            karar_nedenleri.append("Fiyat VWAP uzerinde")
        elif vwap20_durum == "ALTINDA":
            sat_puani += 10

        # BOLLINGER
        if boll_durum == "ALT_BANDA_YAKIN":
            al_puani += 4
        elif boll_durum == "ALT_BANT_ALTI":
            al_puani += 2
            sat_puani += 4
        elif boll_durum == "UST_BANDA_YAKIN":
            sat_puani += 4
        elif boll_durum == "UST_BANT_USTU":
            sat_puani += 8

        # GUNLUK MOMENTUM
        if 0 < gunluk_degisim <= 3:
            al_puani += 8
            karar_nedenleri.append("Saglikli pozitif momentum")
        elif 3 < gunluk_degisim <= 5:
            al_puani += 4
        elif gunluk_degisim > 6:
            sat_puani += 8
        elif gunluk_degisim < -3:
            sat_puani += 8

        # RISK / GETIRI
        if risk_getiri >= 2:
            al_puani += 10
            karar_nedenleri.append("Risk getiri guclu")
        elif 0 < risk_getiri < 1:
            al_puani -= 5

        al_puani = max(0, min(100, al_puani))
        sat_puani = max(0, min(100, sat_puani))

        guven_skoru = max(al_puani, sat_puani)

        karar_giris_alt = yarin_alim_alt
        karar_giris_ust = yarin_alim_ust
        karar_hedef = yarin_kar_al
        karar_stop = yarin_stop

        # =====================================================
        # MADDE 44-47 - HABER ETKILI DINAMIK AI KARAR MOTORU
        # =====================================================
        haber_ai_puani = 0.0
        haber_ai_guven = 0.0
        haber_ai_sinifi = "NOTR"
        haber_ai_karar = "IZLE"
        haber_fiyat_teyidi = 0.0
        haber_nihai_ai_puan = float(al_puani)
        haber_seviye_etkisi = 0.0
        haber_ai_aktif = False

        try:
            haber_bilgi = haber_zeka.haber_puani_getir(sembol) or {}

            if isinstance(haber_bilgi, dict):
                haber_ai_puani = float(
                    haber_bilgi.get(
                        "puan",
                        haber_bilgi.get(
                            "haber_puani",
                            haber_bilgi.get("etki_puani", 0)
                        )
                    ) or 0
                )

                haber_ai_guven = float(
                    haber_bilgi.get(
                        "guven",
                        haber_bilgi.get(
                            "haber_guven",
                            haber_bilgi.get("guven_skoru", 0)
                        )
                    ) or 0
                )

                haber_ai_sinifi = str(
                    haber_bilgi.get(
                        "sinif",
                        haber_bilgi.get(
                            "haber_sinifi",
                            haber_bilgi.get("etki_sinifi", "NOTR")
                        )
                    ) or "NOTR"
                )

            elif isinstance(haber_bilgi, (int, float)):
                haber_ai_puani = float(haber_bilgi)

            # Sadece anlamli haber teknik seviyeleri etkilesin.
            makro_canli = canli_makro_puani_getir(
                sembol
            )

            makro_ai_puani = guvenli_float(
                makro_canli.get("makro_puani")
            )

            sektor_ai_puani = guvenli_float(
                makro_canli.get("sektor_puani")
            )

            haber_ai_aktif = (
                (
                    abs(haber_ai_puani) >= 0.5
                    and haber_ai_guven >= 25
                )
                or abs(makro_ai_puani) >= 0.5
                or abs(sektor_ai_puani) >= 0.5
            )

            if haber_ai_aktif:
                vwap_ai_ustu = None

                if vwap20_durum == "USTUNDE":
                    vwap_ai_ustu = True
                elif vwap20_durum == "ALTINDA":
                    vwap_ai_ustu = False

                direnc_ai = locals().get(
                    "direnÃ§",
                    fiyat + atr14 * 2
                )

                haber_ai_sonuc = (
                    haber_etki_motoru.hisse_haber_ai_guncelle(
                        teknik_puan=al_puani,
                        fiyat=fiyat,
                        atr=atr14,
                        destek=destek,
                        direnc=direnc_ai,
                        haber_puani=haber_ai_puani,
                        haber_guven=haber_ai_guven,
                        sektor_puani=canli_makro_puani_getir(sembol).get(
                            "sektor_puani",
                            0
                        ),
                        makro_puani=canli_makro_puani_getir(sembol).get(
                            "makro_puani",
                            0
                        ),
                        fiyat_degisim_yuzde=gunluk_degisim,
                        hacim_orani=hacim_orani,
                        vwap_ustu=vwap_ai_ustu,
                        obv_pozitif=None,
                        piyasa_rejimi=0,
                        haber_dakika=0,
                        ogrenilmis_katsayi=1.0,
                    )
                )

                haber_ai_karar = haber_ai_sonuc.get(
                    "ai_karar",
                    "IZLE"
                )

                haber_fiyat_teyidi = float(
                    haber_ai_sonuc.get(
                        "fiyat_teyidi",
                        0
                    ) or 0
                )

                haber_nihai_ai_puan = float(
                    haber_ai_sonuc.get(
                        "nihai_ai_puan",
                        al_puani
                    ) or al_puani
                )

                haber_seviye_etkisi = float(
                    haber_ai_sonuc.get(
                        "haber_seviye_etkisi",
                        0
                    ) or 0
                )

                # Haber etkili yeni ALIM / HEDEF / STOP
                karar_giris_alt = float(
                    haber_ai_sonuc.get(
                        "alim_alt",
                        karar_giris_alt
                    )
                )

                karar_giris_ust = float(
                    haber_ai_sonuc.get(
                        "alim_ust",
                        karar_giris_ust
                    )
                )

                karar_hedef = float(
                    haber_ai_sonuc.get(
                        "hedef",
                        karar_hedef
                    )
                )

                karar_stop = float(
                    haber_ai_sonuc.get(
                        "stop",
                        karar_stop
                    )
                )

                karar_nedenleri.append(
                    f"Haber AI: {haber_ai_puani:+.1f}/10 "
                    f"| Guven %{haber_ai_guven:.0f} "
                    f"| Nihai AI {haber_nihai_ai_puan:.1f}"
                )

        except Exception as haber_ai_hata:
            # Haber motorundaki gecici hata teknik motoru durdurmasin.
            haber_ai_aktif = False

        karar_risk = max(
            0,
            ((fiyat - karar_stop) / fiyat) * 100
        )

        karar_getiri = max(
            0,
            ((karar_hedef - fiyat) / fiyat) * 100
        )

        karar_rr = (
            karar_getiri / karar_risk
            if karar_risk > 0
            else 0
        )

        # Nihai karar R/R hesaplandiktan sonra verilir.
        if (
            al_puani >= 65
            and al_puani >= sat_puani + 20
            and karar_rr >= 1.50
        ):
            karar = "AL"

        elif (
            sat_puani >= 60
            and sat_puani >= al_puani + 20
        ):
            karar = "SAT"

        else:
            karar = "IZLE"

        # Anlamli haber varsa AI nihai karara kontrollu mudahale eder.
        if haber_ai_aktif:
            if haber_ai_karar == "GUCLU_AL_ADAYI":
                karar = "AL"

            elif haber_ai_karar == "AL":
                # Cok guclu SAT teknik sinyali varsa tek haberle ezme.
                if sat_puani < 75:
                    karar = "AL"

            elif haber_ai_karar == "SAT":
                karar = "SAT"

            elif haber_ai_karar == "RISKLI_IZLE":
                if karar == "AL":
                    karar = "IZLE"

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
            "vwap20": vwap20,
            "vwap20_uzaklik": vwap20_uzaklik,
            "vwap20_durum": vwap20_durum,
            "boll_alt": boll_alt,
            "boll_orta": boll_orta,
            "boll_ust": boll_ust,
            "boll_genislik": boll_genislik,
            "boll_konum": boll_konum,
            "boll_durum": boll_durum,
            "yarin_alim_alt": yarin_alim_alt,
            "yarin_alim_ust": yarin_alim_ust,
            "yarin_kar_al": yarin_kar_al,
            "yarin_satim_alt": yarin_satim_alt,
            "yarin_satim_ust": yarin_satim_ust,
            "yarin_stop": yarin_stop,
            "yarin_kirilim": yarin_kirilim,
            "yarin_kirilim_hedef": yarin_kirilim_hedef,
            "hacimli_kirilim_durum": hacimli_kirilim_durum,

            # MADDE 7 - KARAR MOTORU
            "karar": karar,
            "guven_skoru": guven_skoru,
            "al_puani": al_puani,
            "sat_puani": sat_puani,
            "karar_giris_alt": karar_giris_alt,
            "karar_giris_ust": karar_giris_ust,
            "karar_hedef": karar_hedef,
            "karar_stop": karar_stop,
            "karar_risk": karar_risk,
            "karar_getiri": karar_getiri,
            "karar_rr": karar_rr,
            "karar_nedenleri": karar_nedenleri,

            # HABER / KAP AI
            "haber_ai_aktif": haber_ai_aktif,
            "haber_puani": round(haber_ai_puani, 2),
            "haber_guven": round(haber_ai_guven, 1),
            "haber_sinifi": haber_ai_sinifi,
            "haber_fiyat_teyidi": round(haber_fiyat_teyidi, 2),
            "haber_ai_karar": haber_ai_karar,
            "nihai_ai_puan": round(haber_nihai_ai_puan, 1),
            "haber_seviye_etkisi": round(haber_seviye_etkisi, 3),
            "makro_puani": canli_makro_puani_getir(sembol).get(
                "makro_puani",
                0
            ),
            "sektor_puani": canli_makro_puani_getir(sembol).get(
                "sektor_puani",
                0
            ),
            "makro_sektor": canli_makro_puani_getir(sembol).get(
                "sektor",
                ""
            ),

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
        return "NOTR"

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

    kapanis = guvenli_float(a.get("kapanis_pozisyonu"))

    # -----------------------------------------------------
    # VERI / ASIRI GUNLUK HAREKET KORUMASI
    # -----------------------------------------------------

    if fiyat <= 0 or rsi <= 0:
        return "NOTR"

    if degisim >= 8 or degisim <= -8:
        return "NOTR"

    # -----------------------------------------------------
    # ASIRI ALIM
    # RSI yuksek; agresif AL ile karismasin.
    # -----------------------------------------------------

    if rsi >= 70:
        return "ASIRI_ALIM"

    # -----------------------------------------------------
    # ASIRI SATIM / TEPKI
    # RSI<30 TEK BASINA YETERLI DEGIL.
    # En az 2 toparlanma teyidi aranir.
    # -----------------------------------------------------

    if rsi < 30:

        teyit = 0

        if rsi_onceki > 0 and rsi > rsi_onceki:
            teyit += 1

        if hist > hist_onceki:
            teyit += 1

        if pozitif_mum:
            teyit += 1

        if kapanis >= 40:
            teyit += 1

        if hacim >= 90:
            teyit += 1

        if macd > signal:
            teyit += 1

        # Sert dusen hisseyi tepki adayi yapma
        if degisim <= -4:
            return "NOTR"

        # Tepkinin buyuk kismi zaten gerceklesti ise gec kalmis sinyal verme
        if degisim > 4:
            return "NOTR"

        # Cok zayif hacimli tepkiyi guvenilir kabul etme
        if hacim < 50:
            return "NOTR"

        # Gercek tepki baslangici icin daha guclu teyit
        if teyit >= 3 and kapanis >= 35:
            return "ASIRI_SATIM"

        return "NOTR"

    # -----------------------------------------------------
    # AGRESIF AL
    # -----------------------------------------------------

    alis = 0

    if 35 <= rsi < 68:

        if macd > signal:
            alis += 2

        if hist > 0:
            alis += 2

        if yukari_kesisim:
            alis += 3

        if sma20 > 0 and fiyat > sma20:
            alis += 2

        if sma50 > 0 and sma20 > sma50:
            alis += 2

        if hacim >= 150:
            alis += 2
        elif hacim >= 120:
            alis += 1

        if pozitif_mum:
            alis += 1

        if 0 < degisim <= 4:
            alis += 2
        elif 4 < degisim <= 6:
            alis += 0
        elif degisim > 6:
            alis -= 4

    if alis >= 9 and degisim > -2:
        return "AGRESIF_ALIS"

    # -----------------------------------------------------
    # AGRESIF SAT
    # -----------------------------------------------------

    satis = 0

    if 32 <= rsi < 68:

        if macd < signal:
            satis += 2

        if hist < 0:
            satis += 2

        if asagi_kesisim:
            satis += 3

        if sma20 > 0 and fiyat < sma20:
            satis += 2

        if sma50 > 0 and sma20 < sma50:
            satis += 2

        if hacim >= 150:
            satis += 2
        elif hacim >= 120:
            satis += 1

        if negatif_mum:
            satis += 1

        if -4 <= degisim < 0:
            satis += 2
        elif -6 <= degisim < -4:
            satis += 0
        elif degisim < -6:
            satis -= 4

    if satis >= 9 and degisim < 0:
        return "AGRESIF_SATIS"

    return "NOTR"


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

def web_verisi_kaydet(sonuclar, tum_semboller=None):

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

            veri["analiz_durumu"] = "HAZIR"
            web_hisseler.append(veri)

        # Analizi o anda alinamayan hisseler de Hisse Ara'da kaybolmasin.
        if tum_semboller:
            analizli = {
                str(x.get("sembol", "")).strip().upper()
                for x in web_hisseler
                if isinstance(x, dict)
            }

            for sembol in tum_semboller:
                kod = str(sembol).strip().upper()

                if not kod or kod in analizli:
                    continue

                web_hisseler.append({
                    "sembol": kod,
                    "analiz_durumu": "VERI_YOK",
                    "veri_mesaji": "Analiz verisi su anda alinamadi."
                })

        web_hisseler.sort(
            key=lambda x: str(x.get("sembol", "")).upper()
        )

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



def yarin_top10_kilitli_oku():
    try:
        if not os.path.exists(YARIN_TOP10_FILE):
            return None

        with open(YARIN_TOP10_FILE, "r", encoding="utf-8") as f:
            veri = json.load(f)

        if not isinstance(veri, dict):
            return None

        return veri

    except Exception as e:
        print("YARIN TOP10 OKUMA HATASI:", e)
        return None


def yarin_top10_kilitli_kaydet(sonuclar, toplam_hisse):
    try:
        top10 = yarin_top10_listesi(sonuclar)

        kayitlar = []

        for sira, (skor, a) in enumerate(top10, 1):
            hisse = dict(a)

            hisse["yarin_top10_sira"] = sira
            hisse["yarin_top10_puani"] = skor

            # Kilitlenen ilk listede henuz ilk hacimli kirilim
            # saati bilinmiyor. Gun ici takip sistemi daha sonra
            # bu alani ilk gerceklesme aninda dolduracak.
            hisse["ilk_hacimli_kirilim_saati"] = None

            kayitlar.append(hisse)

        simdi = datetime.now()

        veri = {
            "olusturma_zamani": simdi.strftime("%Y-%m-%d %H:%M:%S"),
            "analiz_tarihi": simdi.strftime("%Y-%m-%d"),
            "kilitli": True,
            "toplam_hisse": toplam_hisse,
            "teknik_aday": len([
                a for a in sonuclar
                if yarin_potansiyel_hesapla(a) >= 55
            ]),
            "top10": kayitlar
        }

        os.makedirs(
            os.path.dirname(YARIN_TOP10_FILE),
            exist_ok=True
        )

        with open(
            YARIN_TOP10_FILE,
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

        print(
            f"YARIN TOP10 KILITLENDI: "
            f"{len(kayitlar)} hisse"
        )

        return veri

    except Exception as e:
        print("YARIN TOP10 KILITLEME HATASI:", e)
        return None

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

    # -------------------------------------------------
    # 1. TUR - HIZLI TAM BIST TARAMASI
    # -------------------------------------------------

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
                    f"ANALIZ 1. TUR: {tamamlanan}/{toplam}"
                )

    ilk_tur_basarili = len(sonuclar)

    analizli_semboller = {
        str(x.get("sembol", "")).strip().upper()
        for x in sonuclar
        if isinstance(x, dict)
    }

    basarisiz_semboller = [
        sembol
        for sembol in semboller
        if str(sembol).strip().upper()
        not in analizli_semboller
    ]

    print(
        f"1. TUR TAMAMLANDI: "
        f"{ilk_tur_basarili}/{toplam} basarili"
    )

    print(
        f"2. TUR TEKRAR DENENECEK: "
        f"{len(basarisiz_semboller)} hisse"
    )

    # -------------------------------------------------
    # 2. TUR - BASARISIZ HISSELERI DAHA SAKIN TEKRAR DENE
    # -------------------------------------------------

    kurtarilan = 0

    if basarisiz_semboller:

        retry_tamamlanan = 0

        with ThreadPoolExecutor(
            max_workers=4
        ) as executor:

            futures = {
                executor.submit(
                    analiz_et,
                    sembol
                ): sembol
                for sembol in basarisiz_semboller
            }

            for future in as_completed(futures):

                retry_tamamlanan += 1

                try:

                    analiz = future.result()

                    if analiz:

                        kod = str(
                            analiz.get("sembol", "")
                        ).strip().upper()

                        if (
                            kod
                            and kod not in analizli_semboller
                        ):
                            sonuclar.append(analiz)
                            analizli_semboller.add(kod)
                            kurtarilan += 1

                except Exception:
                    pass

                if retry_tamamlanan % 25 == 0:
                    print(
                        f"ANALIZ 2. TUR: "
                        f"{retry_tamamlanan}/"
                        f"{len(basarisiz_semboller)}"
                    )

    veri_alinamayan = max(
        0,
        toplam - len(analizli_semboller)
    )

    print("")
    print("========== TARAMA OZETI ==========")
    print(f"Toplam BIST          : {toplam}")
    print(f"Ilk tur basarili     : {ilk_tur_basarili}")
    print(f"Ikinci tur kurtarilan: {kurtarilan}")
    print(f"Toplam analizli      : {len(analizli_semboller)}")
    print(f"Veri alinamayan      : {veri_alinamayan}")
    print(f"Hisse Ara sembol     : {toplam}")
    print("==================================")
    print("")

    web_verisi_kaydet(
        sonuclar,
        semboller
    )

    tahminleri_kaydet(
        sonuclar,
        toplam
    )

    # YARIN TOP10 KAPANIS KILIDI
    # 18:15'ten onceki taramalar kilitli listeyi degistirmez.
    # Ayni gun liste bir kez olusturulduysa tekrar yazilmaz.
    simdi_dt = datetime.now()

    if (
        simdi_dt.weekday() < 5
        and (simdi_dt.hour, simdi_dt.minute) >= (18, 15)
    ):
        mevcut_kilit = yarin_top10_kilitli_oku()
        bugun = simdi_dt.strftime("%Y-%m-%d")

        if (
            not mevcut_kilit
            or mevcut_kilit.get("analiz_tarihi") != bugun
        ):
            yarin_top10_kilitli_kaydet(
                sonuclar,
                toplam
            )
        else:
            print(
                "YARIN TOP10 ZATEN BUGUN KILITLENDI - "
                "LISTE DEGISTIRILMEDI"
            )

    return (
        sonuclar,
        toplam
    )


# =========================================================
# ÖZET MESAJI
# =========================================================

def ozet_mesaji(a):

    trend = trend_yorumu(a["fiyat"], a["sma20"], a["sma50"])
    rsi_y = rsi_yorumu(a["rsi"])
    hacim_y = hacim_yorumu(a["hacim_orani"])
    macd_y = macd_yorumu(a["macd"], a["signal"], a["hist"])

    # HABER / KAP AI
    try:
        haber_ai = haber_zeka.haber_puani_getir(a.get("sembol"))
        haber_puani = guvenli_float(haber_ai.get("puan"))
        haber_guven = guvenli_float(haber_ai.get("guven"))
        haber_sinifi = haber_ai.get("sinif", "NOTR")
        haber_adet = int(haber_ai.get("adet", 0) or 0)

        haber_birlesik = haber_zeka.teknik_haber_birlestir(
            a.get("puan", 0),
            haber_puani,
            haber_guven
        )

        haber_nihai_ai = guvenli_float(
            haber_birlesik.get("nihai_puan", a.get("puan", 0))
        )

    except Exception:
        haber_puani = 0
        haber_guven = 0
        haber_sinifi = "NOTR"
        haber_adet = 0
        haber_nihai_ai = guvenli_float(a.get("puan", 0))

    durum = a.get("hacimli_kirilim_durum", "BEKLENIYOR")

    if durum == "GERCEKLESTI":
        kirilim_yazi = "\U0001F7E2 Hacimli k\u0131r\u0131l\u0131m ger\u00e7ekle\u015fti"
    elif durum == "HACIM_ZAYIF":
        kirilim_yazi = "\U0001F7E1 Fiyat k\u0131rd\u0131 ancak hacim teyidi zay\u0131f"
    else:
        kirilim_yazi = "\u26aa Hacimli k\u0131r\u0131l\u0131m bekleniyor"

    return (
        f"\U0001F4CA {a['sembol']} DETAYLI H\u0130SSE \u00d6ZET\u0130\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"

        f"\U0001F4B0 Fiyat: {a['fiyat']:.2f} TL\n"
        f"\U0001F4C8 G\u00fcnl\u00fck: {a['degisim']:+.2f}%\n"
        f"\U0001F53A G\u00fcnl\u00fck Y\u00fcksek: {a['yuksek']:.2f}\n"
        f"\U0001F53B G\u00fcnl\u00fck D\u00fc\u015f\u00fck: {a['dusuk']:.2f}\n"
        f"\U0001F535 A\u00e7\u0131l\u0131\u015f: {a['acilis']:.2f}\n"
        f"\U0001F4E6 Hacim: {a['hacim']:,.0f}\n\n"

        f"\U0001F4CA TEKN\u0130K G\u00d6STERGELER\n"
        f"RSI(14): {a['rsi']:.2f} \u2014 {rsi_y}\n"
        f"SMA20: {a['sma20']:.2f}\n"
        f"SMA50: {a['sma50']:.2f}\n"
        f"Trend: {trend}\n\n"

        f"\U0001F4C9 MACD\n"
        f"MACD: {a['macd']:.4f}\n"
        f"Sinyal: {a['signal']:.4f}\n"
        f"Histogram: {a['hist']:.4f}\n"
        f"{macd_y}\n"
        f"Kesi\u015fim: "
        f"{'\U0001F7E2 YUKARI' if a['yukari_kesisim'] else '\U0001F534 A\u015eA\u011eI' if a['asagi_kesisim'] else '\u26aa YOK'}\n\n"

        f"\U0001F4E6 HAC\u0130M ANAL\u0130Z\u0130\n"
        f"20G Ortalama: {a['hacim20']:,.0f}\n"
        f"Hacim Oran\u0131: %{a['hacim_orani']:.1f}\n"
        f"{hacim_y}\n\n"

        f"\U0001F4CD VWAP ANAL\u0130Z\u0130\n"
        f"VWAP20: {a.get('vwap20', 0):.2f} TL\n"
        f"VWAP Uzakl\u0131k: {a.get('vwap20_uzaklik', 0):+.2f}%\n"
        f"Durum: "
        f"{'\U0001F7E2 VWAP \u00dcZER\u0130NDE' if a.get('vwap20_durum') == 'USTUNDE' else '\U0001F534 VWAP ALTINDA' if a.get('vwap20_durum') == 'ALTINDA' else '\u26aa VWAP SEV\u0130YES\u0130NDE'}\n\n"

        f"\U0001F4CA BOLLINGER BANTLARI (20,2)\n"
        f"Alt Bant: {a.get('boll_alt', 0):.2f} TL\n"
        f"Orta Bant: {a.get('boll_orta', 0):.2f} TL\n"
        f"\u00dcst Bant: {a.get('boll_ust', 0):.2f} TL\n"
        f"Bant Konumu: %{a.get('boll_konum', 0):.1f}\n"
        f"Bant Geni\u015fli\u011fi: %{a.get('boll_genislik', 0):.1f}\n"
        f"Durum: "
        f"{'\U0001F534 \u00dcST BANT \u00dcST\u00dc' if a.get('boll_durum') == 'UST_BANT_USTU' else '\U0001F7E2 ALT BANT ALTI' if a.get('boll_durum') == 'ALT_BANT_ALTI' else '\U0001F7E0 \u00dcST BANDA YAKIN' if a.get('boll_durum') == 'UST_BANDA_YAKIN' else '\U0001F7E1 ALT BANDA YAKIN' if a.get('boll_durum') == 'ALT_BANDA_YAKIN' else '\u26aa BANT \u0130\u00c7\u0130NDE'}\n\n"

        f"\U0001F9F1 DESTEK / D\u0130REN\u00c7\n"
        f"Destek: {a['destek']:.2f}\n"
        f"Diren\u00e7: {a['direnc']:.2f}\n"
        f"\u00dcst Diren\u00e7: {a['direnc60']:.2f}\n\n"

        f"\U0001F3AF ORTA / UZUN VADE\n"
        f"Al\u0131m B\u00f6lgesi: {a['giris_alt']:.2f} - {a['giris_ust']:.2f} TL\n"
        f"Hedef 1: {a['hedef1']:.2f} TL\n"
        f"Hedef 2: {a['hedef2']:.2f} TL\n"
        f"Stop-Loss: {a['stop']:.2f} TL\n"
        f"Risk/Getiri: {a['risk_getiri']:.2f}\n\n"

        f"\U0001F305 YARIN \u0130\u00c7\u0130N\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001F7E2 Al\u0131m B\u00f6lgesi: "
        f"{a.get('yarin_alim_alt', 0):.2f} - "
        f"{a.get('yarin_alim_ust', 0):.2f} TL\n"

        f"\U0001F4B5 K\u0131sa Vade K\u00e2r Al: "
        f"{a.get('yarin_kar_al', 0):.2f} TL\n"

        f"\U0001F7E0 K\u0131sa Vade Sat\u0131\u015f B\u00f6lgesi: "
        f"{a.get('yarin_satim_alt', 0):.2f} - "
        f"{a.get('yarin_satim_ust', 0):.2f} TL\n"

        f"\U0001F6D1 K\u0131sa Vade Stop-Loss: "
        f"{a.get('yarin_stop', 0):.2f} TL\n"

        f"\U0001F680 Hacimli K\u0131r\u0131l\u0131m: "
        f"{a.get('yarin_kirilim', 0):.2f} TL\n"

        f"\U0001F3AF K\u0131r\u0131l\u0131m Sonras\u0131 Hedef: "
        f"{a.get('yarin_kirilim_hedef', 0):.2f} TL\n"

        f"{kirilim_yazi}\n\n"

        f"📰 HABER / KAP AI\n"
        f"━━━━━━━━━━━━━━\n"
        f"Etki: {haber_puani:+.1f}/10\n"
        f"Sınıf: {haber_sinifi}\n"
        f"Haber Güveni: %{haber_guven:.0f}\n"
        f"İzlenen Haber: {haber_adet}\n"
        f"Teknik Skor: {a.get('puan', 0)}/100\n"
        f"🤖 Nihai AI Skoru: {haber_nihai_ai:.0f}/100\n\n"

        f"\U0001F9E0 ALGOR\u0130TMA KARARI\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Karar: "
        f"{'\U0001F7E2 AL' if a.get('karar') == 'AL' else '\U0001F534 SAT' if a.get('karar') == 'SAT' else '\U0001F7E1 \u0130ZLE'}\n"
        f"Teknik G\u00fc\u00e7: {a.get('puan', 0)}/100\n"
        f"G\u00fcven Skoru: {a.get('guven_skoru', 0)}/100\n"
        f"AL / SAT Puan\u0131: {a.get('al_puani', 0)} / {a.get('sat_puani', 0)}\n"
        f"\U0001F4CD Giri\u015f: {a.get('karar_giris_alt', 0):.2f} - {a.get('karar_giris_ust', 0):.2f} TL\n"
        f"\U0001F3AF Hedef: {a.get('karar_hedef', 0):.2f} TL\n"
        f"\U0001F6D1 Stop: {a.get('karar_stop', 0):.2f} TL\n"
        f"Beklenen Getiri: %{a.get('karar_getiri', 0):.2f}\n"
        f"Risk: %{a.get('karar_risk', 0):.2f}\n"
        f"R/R: {a.get('karar_rr', 0):.2f}\n\n"

        f"\u2b50 TEKN\u0130K SKOR: {a['puan']}/100\n\n"

        f"\U0001F50E SKOR NEDENLER\u0130\n"
        + "".join(
            f"\u2022 {n}\n"
            for n in a["nedenler"]
        )
        + "\n"

        f"\u26a0\ufe0f Bu \u00e7\u0131kt\u0131 teknik g\u00f6stergelere dayal\u0131 "
        f"algoritmik analizdir; kesin al\u0131m/sat\u0131m garantisi de\u011fildir."
    )


# =========================================================
# GELISMIS SINYAL MESAJI
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

def agresif_kalite_puani(a, sinif=None):

    if not a:
        return -999

    if sinif is None:
        sinif = sinyal_sinifi(a)

    fiyat = guvenli_float(a.get("fiyat"))
    degisim = guvenli_float(a.get("degisim"))
    rsi = guvenli_float(a.get("rsi"))
    hacim = guvenli_float(a.get("hacim_orani"))
    sma20 = guvenli_float(a.get("sma20"))
    sma50 = guvenli_float(a.get("sma50"))
    macd = guvenli_float(a.get("macd"))
    signal = guvenli_float(a.get("signal"))
    hist = guvenli_float(a.get("hist"))
    risk_getiri = guvenli_float(a.get("risk_getiri"))

    puan = 0

    # -------------------------------------------------
    # AGRESIF AL KALITE PUANI
    # -------------------------------------------------
    if sinif == "AGRESIF_ALIS":

        if hacim >= 150:
            puan += 20
        elif hacim >= 120:
            puan += 16
        elif hacim >= 100:
            puan += 12
        elif hacim >= 80:
            puan += 7
        elif hacim >= 70:
            puan += 3
        else:
            puan -= 10

        if sma20 > 0 and fiyat > sma20:
            puan += 15

        if sma50 > 0 and sma20 > sma50:
            puan += 15

        if macd > signal:
            puan += 15

        if hist > 0:
            puan += 10

        if 42 <= rsi <= 62:
            puan += 10
        elif 35 <= rsi < 42 or 62 < rsi < 68:
            puan += 4

        if 0 < degisim <= 3:
            puan += 10
        elif 3 < degisim <= 4.5:
            puan += 5
        elif 4.5 < degisim <= 6:
            puan -= 5

        if risk_getiri >= 2:
            puan += 5

    # -------------------------------------------------
    # AGRESIF SAT KALITE PUANI
    # -------------------------------------------------
    elif sinif == "AGRESIF_SATIS":

        if hacim >= 150:
            puan += 20
        elif hacim >= 120:
            puan += 16
        elif hacim >= 100:
            puan += 12
        elif hacim >= 80:
            puan += 7
        elif hacim >= 70:
            puan += 3
        else:
            puan -= 10

        if sma20 > 0 and fiyat < sma20:
            puan += 15

        if sma50 > 0 and sma20 < sma50:
            puan += 15

        if macd < signal:
            puan += 15

        if hist < 0:
            puan += 10

        if 35 <= rsi <= 55:
            puan += 10
        elif 30 <= rsi < 35 or 55 < rsi < 68:
            puan += 4

        if -3 <= degisim < 0:
            puan += 10
        elif -4.5 <= degisim < -3:
            puan += 5
        elif -6 <= degisim < -4.5:
            puan -= 5

    else:
        return -999

    return max(0, min(100, round(puan)))


def guclu_agresif_mi(a):

    sinif = sinyal_sinifi(a)

    if sinif not in ("AGRESIF_ALIS", "AGRESIF_SATIS"):
        return False

    hacim = guvenli_float(a.get("hacim_orani"))
    skor = agresif_kalite_puani(a, sinif)

    # Kalite kapisi
    if hacim < 70:
        return False

    return skor >= 60


def agresif_mesaji(sonuclar, toplam):

    ham_alis = []
    ham_satis = []
    guclu_alis = []
    guclu_satis = []

    for a in sonuclar:

        sinif = sinyal_sinifi(a)

        if sinif == "AGRESIF_ALIS":

            ham_alis.append(a)
            skor = agresif_kalite_puani(a, sinif)

            if guclu_agresif_mi(a):
                guclu_alis.append((skor, a))

        elif sinif == "AGRESIF_SATIS":

            ham_satis.append(a)
            skor = agresif_kalite_puani(a, sinif)

            if guclu_agresif_mi(a):
                guclu_satis.append((skor, a))

    guclu_alis.sort(
        key=lambda x: x[0],
        reverse=True
    )

    guclu_satis.sort(
        key=lambda x: x[0],
        reverse=True
    )

    mesaj = (
        "AGRESIF HISSELER\n"
        "====================\n\n"
        f"Taranan hisse: {toplam}\n"
        f"Ham Agresif AL: {len(ham_alis)}\n"
        f"Guclu Agresif AL: {len(guclu_alis)}\n"
        f"Ham Agresif SAT: {len(ham_satis)}\n"
        f"Guclu Agresif SAT: {len(guclu_satis)}\n\n"
    )

    mesaj += "GUCLU AGRESIF AL - TOP 10\n"
    mesaj += "--------------------\n\n"

    if guclu_alis:

        for i, (skor, a) in enumerate(guclu_alis[:10], 1):

            risk = ""

            if guvenli_float(a.get("degisim")) > 5:
                risk = " | UYARI: Gun icinde fazla kosmus"

            mesaj += (
                f"{i}. {a['sembol']} - Kalite {skor}/100\n"
                f"   Fiyat {a['fiyat']:.2f} TL | "
                f"Gunluk {a['degisim']:+.2f}%{risk}\n"
                f"   RSI {a['rsi']:.1f} | "
                f"Hacim %{a['hacim_orani']:.0f}\n"
                f"   Hedef1 {a['hedef1']:.2f} | "
                f"Stop {a['stop']:.2f}\n\n"
            )

    else:
        mesaj += "Guclu AL adayi bulunamadi.\n\n"

    mesaj += "GUCLU AGRESIF SAT - TOP 10\n"
    mesaj += "---------------------\n\n"

    if guclu_satis:

        for i, (skor, a) in enumerate(guclu_satis[:10], 1):

            mesaj += (
                f"{i}. {a['sembol']} - Kalite {skor}/100\n"
                f"   Fiyat {a['fiyat']:.2f} TL | "
                f"Gunluk {a['degisim']:+.2f}%\n"
                f"   RSI {a['rsi']:.1f} | "
                f"Hacim %{a['hacim_orani']:.0f}\n"
                f"   Asagi yonlu momentum\n\n"
            )

    else:
        mesaj += "Guclu SAT adayi bulunamadi.\n\n"

    mesaj += (
        "Ham adaylar sinyal motorundan gelir.\n"
        "Guclu adaylar ikinci kalite suzgecinden gecer.\n"
        "Agresif AL ve Agresif SAT ayri puanlanir."
    )

    return mesaj


# =========================================================
# GUN ICI TOP 10
# =========================================================

class GunIciMultiSessionStream(bp.TradingViewStream):
    """Tek WebSocket uzerinde her hisse icin ayri chart session acar."""

    def __init__(self):
        super().__init__()
        self._gun_ici_sessions = {}

    def subscribe_multi(self, symbol, interval="5m", exchange="BIST"):
        tv_interval = {
            "1m": "1", "5m": "5", "15m": "15",
            "30m": "30", "1h": "60", "1d": "1D"
        }.get(interval, interval)

        session_id = self._generate_session_id("cs")
        self._gun_ici_sessions[session_id] = (symbol, interval)

        if symbol not in self._chart_data:
            self._chart_data[symbol] = {}
        self._chart_data[symbol][interval] = []

        self._send(self._create_message("chart_create_session", [session_id]))

        resolve_id = "ser_1"
        price_id = "$prices"
        series_index = "s1"
        symbol_config = json.dumps({
            "symbol": f"{exchange}:{symbol}",
            "adjustment": "splits",
            "session": "regular",
        })

        self._send(self._create_message(
            "resolve_symbol", [session_id, resolve_id, f"={symbol_config}"]
        ))
        self._send(self._create_message(
            "create_series",
            [session_id, price_id, series_index, resolve_id, tv_interval, 300]
        ))

    def _handle_chart_data(self, params):
        if len(params) < 2:
            return

        session_id = params[0]
        data = params[1]
        if session_id not in self._gun_ici_sessions or not isinstance(data, dict):
            return

        symbol, interval = self._gun_ici_sessions[session_id]
        candles = []

        for series_data in data.values():
            if not isinstance(series_data, dict):
                continue
            bars = series_data.get("s", series_data.get("st", []))
            if not isinstance(bars, list):
                continue

            for bar in bars:
                if isinstance(bar, dict) and "v" in bar:
                    v = bar["v"]
                    if len(v) >= 5:
                        candles.append({
                            "time": int(v[0]),
                            "open": float(v[1]),
                            "high": float(v[2]),
                            "low": float(v[3]),
                            "close": float(v[4]),
                            "volume": float(v[5]) if len(v) >= 6 and v[5] else 0,
                        })

        if candles:
            self._update_chart_data(symbol, interval, candles)


def gun_ici_mumlari_dataframe(mumlar):
    if not mumlar:
        return pd.DataFrame()

    veri = pd.DataFrame(mumlar)
    gerekli = {"time", "open", "high", "low", "close", "volume"}
    if not gerekli.issubset(veri.columns):
        return pd.DataFrame()

    # TradingView epoch zamanini Istanbul saatine ceviriyoruz.
    zaman = pd.to_datetime(veri["time"], unit="s", utc=True)
    veri.index = zaman.dt.tz_convert("Europe/Istanbul")

    veri = veri.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume"
    })
    return veri[["Open", "High", "Low", "Close", "Volume"]].sort_index()


def gun_ici_stream_verileri_getir(semboller, paket_boyutu=100, bekleme=10):
    """5 dk verilerini 100'erli paketlerle toplar."""
    veri_map = {}
    basarisiz = []
    toplam_paket = (len(semboller) + paket_boyutu - 1) // paket_boyutu

    for bas in range(0, len(semboller), paket_boyutu):
        paket = semboller[bas:bas + paket_boyutu]
        paket_no = bas // paket_boyutu + 1
        print(f"STREAM PAKET {paket_no}/{toplam_paket}: {len(paket)} hisse")

        stream = GunIciMultiSessionStream()
        try:
            stream.connect()
            for sembol in paket:
                stream.subscribe_multi(sembol, "5m", "BIST")

            time.sleep(bekleme)

            for sembol in paket:
                mumlar = stream._chart_data.get(sembol, {}).get("5m", [])
                df = gun_ici_mumlari_dataframe(mumlar)
                if df is not None and not df.empty:
                    veri_map[sembol] = df
                else:
                    basarisiz.append(sembol)
        except Exception as e:
            print(f"STREAM PAKET HATASI {paket_no}: {e}")
            basarisiz.extend([s for s in paket if s not in veri_map])
        finally:
            try:
                stream.disconnect()
            except Exception:
                pass

        if bas + paket_boyutu < len(semboller):
            time.sleep(1)

    # Tekrarlari temizle, sirayi koru.
    basarisiz = list(dict.fromkeys(basarisiz))
    print(f"STREAM SONUCU | BASARILI: {len(veri_map)} | BASARISIZ: {len(basarisiz)}")
    return veri_map, basarisiz



def ilk_hacimli_kirilim_bul(veri, kirilim_seviyesi):
    """
    5 dakikalik mumlari sirayla kontrol eder.
    Ilk kez kirilim seviyesinin uzerinde kapanan ve
    hacmi onceki 20 adet 5 dk mum ortalamasinin
    en az %130'u olan mumun saatini dondurur.
    """

    try:
        if veri is None or veri.empty:
            return None, "BEKLENIYOR"

        seviye = guvenli_float(kirilim_seviyesi)

        if seviye <= 0:
            return None, "BEKLENIYOR"

        veri = veri.dropna(
            subset=["Open", "High", "Low", "Close", "Volume"]
        ).copy()

        if veri.empty:
            return None, "BEKLENIYOR"

        # Yalnizca son islem gununun mumlari.
        son_tarih = veri.index[-1].date()

        bugun = veri[
            veri.index.date == son_tarih
        ].copy()

        if len(bugun) < 2:
            return None, "BEKLENIYOR"

        fiyat_kirdi = False

        for i in range(1, len(bugun)):

            onceki_kapanis = guvenli_float(
                bugun["Close"].iloc[i - 1]
            )

            kapanis = guvenli_float(
                bugun["Close"].iloc[i]
            )

            # Kapanis bazli gercek yukari gecis.
            yeni_kirilim = (
                onceki_kapanis <= seviye
                and kapanis > seviye
            )

            if not yeni_kirilim:
                continue

            fiyat_kirdi = True

            # Mumun kendisini ortalamaya katmiyoruz.
            onceki_hacimler = bugun["Volume"].iloc[
                max(0, i - 20):i
            ].astype(float)

            # Saglikli hacim teyidi icin en az 3 onceki mum.
            if len(onceki_hacimler) < 3:
                continue

            ort_hacim = guvenli_float(
                onceki_hacimler.mean()
            )

            mum_hacmi = guvenli_float(
                bugun["Volume"].iloc[i]
            )

            if ort_hacim <= 0:
                continue

            hacim_orani = (
                mum_hacmi / ort_hacim
            ) * 100

            if hacim_orani >= 130:

                saat = bugun.index[i].strftime(
                    "%H:%M"
                )

                return saat, "GERCEKLESTI"

        if fiyat_kirdi:
            return None, "HACIM_ZAYIF"

        return None, "BEKLENIYOR"

    except Exception as e:
        print(
            "ILK HACIMLI KIRILIM HATASI:",
            e
        )
        return None, "BEKLENIYOR"



def gun_ici_analiz_hesapla(sembol, veri=None):
    """
    5 dakikalik mumlarla gun ici guc analizi.
    Yarin TOP 10 algoritmasindan tamamen ayridir.
    """

    try:
        # Stream taramasinda veri disaridan gelir.
        # Geriye donuk uyumluluk icin veri verilmezse eski Ticker yolu calisir.
        if veri is None:
            hisse = bp.Ticker(sembol)
            veri = hisse.history(
                period="1d",
                interval="5m"
            )

        if veri is None or veri.empty:
            return None

        if len(veri) < 30:
            return None

        veri = veri.dropna(
            subset=["Open", "High", "Low", "Close", "Volume"]
        )

        if len(veri) < 30:
            return None

        # Son mumun ait oldugu islem gunu.
        son_tarih = veri.index[-1].date()

        bugun = veri[
            veri.index.date == son_tarih
        ].copy()

        if bugun.empty or len(bugun) < 3:
            return {
                "_durum": "YETERSIZ_GUNICI_VERI",
                "sembol": sembol,
                "_mum_sayisi": len(bugun),
                "_son_veri_tarihi": str(veri.index[-1])
            }

        close = veri["Close"].astype(float)
        volume = veri["Volume"].astype(float)

        son = bugun.iloc[-1]

        fiyat = guvenli_float(
            son["Close"]
        )

        gun_acilis = guvenli_float(
            bugun.iloc[0]["Open"]
        )

        gun_yuksek = guvenli_float(
            bugun["High"].max()
        )

        gun_dusuk = guvenli_float(
            bugun["Low"].min()
        )

        if fiyat <= 0 or gun_acilis <= 0:
            return None

        # Gunluk degisim: gunun ilk 5 dk acilisina gore.
        acilisa_gore_degisim = (
            (fiyat - gun_acilis)
            / gun_acilis
        ) * 100

        # Gun ici dipten toparlanma.
        if gun_dusuk > 0:
            dipten_toparlanma = (
                (fiyat - gun_dusuk)
                / gun_dusuk
            ) * 100
        else:
            dipten_toparlanma = 0

        # Gun ici zirveye uzaklik.
        if gun_yuksek > 0:
            zirveye_uzaklik = (
                (gun_yuksek - fiyat)
                / gun_yuksek
            ) * 100
        else:
            zirveye_uzaklik = 0

        # -------------------------------------------------
        # GERCEK SEANS VWAP - 5 DAKIKA
        # -------------------------------------------------
        bugun_high = bugun["High"].astype(float)
        bugun_low = bugun["Low"].astype(float)
        bugun_close = bugun["Close"].astype(float)
        bugun_volume = bugun["Volume"].astype(float)

        tipik_fiyat = (
            bugun_high + bugun_low + bugun_close
        ) / 3.0

        toplam_seans_hacmi = guvenli_float(
            bugun_volume.sum()
        )

        if toplam_seans_hacmi > 0:
            seans_vwap = guvenli_float(
                (tipik_fiyat * bugun_volume).sum()
                / toplam_seans_hacmi
            )
        else:
            seans_vwap = fiyat

        if seans_vwap > 0:
            seans_vwap_uzaklik = (
                (fiyat - seans_vwap)
                / seans_vwap
            ) * 100
        else:
            seans_vwap_uzaklik = 0

        # -------------------------------------------------
        # RSI 14 - 5 DAKIKA
        # -------------------------------------------------

        delta = close.diff()

        kazanc = delta.clip(
            lower=0
        )

        kayip = -delta.clip(
            upper=0
        )

        ort_kazanc = kazanc.rolling(14).mean()
        ort_kayip = kayip.rolling(14).mean()

        son_kazanc = guvenli_float(
            ort_kazanc.iloc[-1]
        )

        son_kayip = guvenli_float(
            ort_kayip.iloc[-1]
        )

        if son_kayip == 0:
            rsi5 = 100 if son_kazanc > 0 else 50
        else:
            rs = son_kazanc / son_kayip
            rsi5 = 100 - (100 / (1 + rs))

        # -------------------------------------------------
        # MACD - 5 DAKIKA
        # -------------------------------------------------

        ema12 = close.ewm(
            span=12,
            adjust=False
        ).mean()

        ema26 = close.ewm(
            span=26,
            adjust=False
        ).mean()

        macd_seri = ema12 - ema26

        signal_seri = macd_seri.ewm(
            span=9,
            adjust=False
        ).mean()

        hist_seri = macd_seri - signal_seri

        macd5 = guvenli_float(
            macd_seri.iloc[-1]
        )

        signal5 = guvenli_float(
            signal_seri.iloc[-1]
        )

        hist5 = guvenli_float(
            hist_seri.iloc[-1]
        )

        hist_onceki = guvenli_float(
            hist_seri.iloc[-2]
        )

        # -------------------------------------------------
        # MADDE 33 - KISA EMA / OBV / ATR
        # -------------------------------------------------

        # EMA 9 ve EMA 21 - 5 dakika
        ema9_seri = close.ewm(
            span=9,
            adjust=False
        ).mean()

        ema21_seri = close.ewm(
            span=21,
            adjust=False
        ).mean()

        ema9_5 = guvenli_float(
            ema9_seri.iloc[-1]
        )

        ema21_5 = guvenli_float(
            ema21_seri.iloc[-1]
        )

        if ema21_5 > 0:
            ema_fark_yuzde = (
                (ema9_5 - ema21_5)
                / ema21_5
            ) * 100
        else:
            ema_fark_yuzde = 0

        # OBV - On Balance Volume
        yon = close.diff()

        obv_hareket = volume.copy() * 0.0
        obv_hareket[yon > 0] = volume[yon > 0]
        obv_hareket[yon < 0] = -volume[yon < 0]

        obv_seri = obv_hareket.cumsum()

        obv5 = guvenli_float(
            obv_seri.iloc[-1]
        )

        if len(obv_seri) >= 4:
            obv_15dk_once = guvenli_float(
                obv_seri.iloc[-4]
            )

            obv_degisim_15dk = (
                obv5 - obv_15dk_once
            )
        else:
            obv_degisim_15dk = 0

        if obv_degisim_15dk > 0:
            obv_durum = "YUKSELEN"
        elif obv_degisim_15dk < 0:
            obv_durum = "DUSEN"
        else:
            obv_durum = "YATAY"

        # ATR(14) - 5 dakika
        high5 = veri["High"].astype(float)
        low5 = veri["Low"].astype(float)
        prev_close5 = close.shift(1)

        tr1 = high5 - low5
        tr2 = (high5 - prev_close5).abs()
        tr3 = (low5 - prev_close5).abs()

        true_range5 = tr1.to_frame("tr1")
        true_range5["tr2"] = tr2
        true_range5["tr3"] = tr3

        tr5 = true_range5.max(axis=1)

        atr14_5 = guvenli_float(
            tr5.rolling(14).mean().iloc[-1]
        )

        if fiyat > 0:
            atr14_5_yuzde = (
                atr14_5 / fiyat
            ) * 100
        else:
            atr14_5_yuzde = 0

        if atr14_5_yuzde >= 1.50:
            oynaklik_durumu = "YUKSEK"
        elif atr14_5_yuzde >= 0.70:
            oynaklik_durumu = "ORTA"
        else:
            oynaklik_durumu = "DUSUK"

        # -------------------------------------------------
        # HACIM HIZLANMASI
        # -------------------------------------------------

        son_hacim = guvenli_float(
            volume.iloc[-1]
        )

        onceki_hacimler = volume.iloc[-21:-1]

        ort_hacim20_5dk = guvenli_float(
            onceki_hacimler.mean()
        )

        if ort_hacim20_5dk > 0:
            hacim_hizlanma = (
                son_hacim
                / ort_hacim20_5dk
            ) * 100
        else:
            hacim_hizlanma = 0

        # Son 3 mum hacmi / onceki 20 mum ortalamasi.
        son3_hacim = guvenli_float(
            volume.iloc[-3:].mean()
        )

        if ort_hacim20_5dk > 0:
            hacim3_orani = (
                son3_hacim
                / ort_hacim20_5dk
            ) * 100
        else:
            hacim3_orani = 0

        # -------------------------------------------------
        # KISA VADE MOMENTUM
        # -------------------------------------------------

        if len(close) >= 4:
            fiyat_15dk_once = guvenli_float(
                close.iloc[-4]
            )

            if fiyat_15dk_once > 0:
                momentum15 = (
                    (fiyat - fiyat_15dk_once)
                    / fiyat_15dk_once
                ) * 100
            else:
                momentum15 = 0
        else:
            momentum15 = 0

        if len(close) >= 7:
            fiyat_30dk_once = guvenli_float(
                close.iloc[-7]
            )

            if fiyat_30dk_once > 0:
                momentum30 = (
                    (fiyat - fiyat_30dk_once)
                    / fiyat_30dk_once
                ) * 100
            else:
                momentum30 = 0
        else:
            momentum30 = 0

        # -------------------------------------------------
        # YAKIN KIRILIM
        # Son tamamlanmis 12 mumun tepesini referans al.
        # Son mumu direncten cikar.
        # -------------------------------------------------

        onceki_mumlar = veri.iloc[-13:-1]

        if not onceki_mumlar.empty:
            yakin_direnc = guvenli_float(
                onceki_mumlar["High"].max()
            )
        else:
            yakin_direnc = gun_yuksek

        kirilim = (
            yakin_direnc > 0
            and fiyat > yakin_direnc
        )

        hacimli_kirilim = (
            kirilim
            and hacim3_orani >= 130
        )

        # -------------------------------------------------
        # PUANLAMA
        # -------------------------------------------------

        puan = 0
        nedenler = []

        # Sert risk filtresi:
        # cok sert eksi veya tavan benzeri hareketi kovalamiyoruz.
        if acilisa_gore_degisim <= -7:
            return {
                "_durum": "FILTRE_DISI",
                "sembol": sembol,
                "_neden": "SERT_EKSI",
                "fiyat": fiyat,
                "acilisa_gore_degisim": acilisa_gore_degisim
            }

        if acilisa_gore_degisim >= 9.5:
            return {
                "_durum": "FILTRE_DISI",
                "sembol": sembol,
                "_neden": "SERT_ARTI",
                "fiyat": fiyat,
                "acilisa_gore_degisim": acilisa_gore_degisim
            }

        # Acilisa gore guc.
        if 0.5 <= acilisa_gore_degisim <= 3:
            puan += 12
            nedenler.append("Acilisa gore guclu")

        elif 3 < acilisa_gore_degisim <= 5:
            puan += 9
            nedenler.append("Pozitif gun ici momentum")

        elif 5 < acilisa_gore_degisim < 8:
            puan += 4

        elif -1 <= acilisa_gore_degisim < 0.5:
            puan += 2

        # Dipten toparlanma.
        if 1 <= dipten_toparlanma <= 4:
            puan += 10
            nedenler.append("Dipten toparlanma")

        elif 4 < dipten_toparlanma <= 7:
            puan += 7

        elif dipten_toparlanma > 7:
            puan += 3

        # Zirveye yakinlik.
        if zirveye_uzaklik <= 0.5:
            puan += 10
            nedenler.append("Gun ici zirveye yakin")

        elif zirveye_uzaklik <= 1.5:
            puan += 7

        elif zirveye_uzaklik <= 3:
            puan += 3

        # RSI.
        if 50 <= rsi5 <= 68:
            puan += 12
            nedenler.append("5dk RSI guclu")

        elif 45 <= rsi5 < 50:
            puan += 6

        elif 68 < rsi5 < 75:
            puan += 4

        elif rsi5 >= 80:
            puan -= 8

        elif rsi5 < 30:
            puan -= 8

        # MACD.
        if macd5 > signal5:
            puan += 9
            nedenler.append("5dk MACD pozitif")

        if hist5 > 0:
            puan += 5

        if hist5 > hist_onceki:
            puan += 5
            nedenler.append("Momentum artiyor")

        # Hacim.
        if hacim3_orani >= 200:
            puan += 15
            nedenler.append("Cok guclu hacim")

        elif hacim3_orani >= 150:
            puan += 12
            nedenler.append("Guclu hacim")

        elif hacim3_orani >= 120:
            puan += 8

        elif hacim3_orani < 60:
            puan -= 5

        # Son 15 / 30 dakika momentum.
        if 0.2 <= momentum15 <= 1.5:
            puan += 6

        elif momentum15 > 1.5:
            puan += 3

        elif momentum15 <= -1:
            puan -= 5

        if 0.3 <= momentum30 <= 2.5:
            puan += 6

        elif momentum30 <= -1.5:
            puan -= 5

        # Kirilim.
        if hacimli_kirilim:
            puan += 15
            nedenler.append("Hacimli kirilim")

        elif kirilim:
            puan += 6
            nedenler.append("Direnc kirilimi")

        puan = max(
            0,
            min(100, puan)
        )

        # =================================================
        # GUN ICI HABER / KAP AI KATKISI
        # =================================================
        teknik_gun_ici_puan = puan

        try:
            haber = haber_zeka.haber_puani_getir(sembol)

            birlesik = haber_zeka.teknik_haber_birlestir(
                teknik_gun_ici_puan,
                haber.get("puan", 0),
                haber.get("guven", 0)
            )

            puan = birlesik.get(
                "nihai_puan",
                teknik_gun_ici_puan
            )

            haber_puani = haber.get("puan", 0)
            haber_guven = haber.get("guven", 0)
            haber_sinifi = haber.get("sinif", "NOTR")

        except Exception:
            puan = teknik_gun_ici_puan
            haber_puani = 0
            haber_guven = 0
            haber_sinifi = "NOTR"

        # -------------------------------------------------
        # GUN ICI ISLEM SEVIYELERI
        # -------------------------------------------------

        gun_aralik = max(
            gun_yuksek - gun_dusuk,
            fiyat * 0.005
        )

        # Alim bolgesi:
        # mevcut fiyat etrafinda kontrollu geri cekilme alani.
        alim_alt = max(
            gun_dusuk,
            fiyat - (gun_aralik * 0.18)
        )

        alim_ust = fiyat

        # Kisa vadeli kar al:
        # gun ici yuksek ve volatilite birlikte dikkate alinir.
        kar_al = max(
            gun_yuksek,
            fiyat + (gun_aralik * 0.35)
        )

        # Stop:
        # alim bolgesinin ve gun ici yapinin altinda.
        stop = max(
            0,
            alim_alt - (gun_aralik * 0.22)
        )

        # -------------------------------------------------
        # GUN ICI KARAR / GUVEN / RISK-GETIRI MOTORU
        # -------------------------------------------------
        gun_ici_al_puani = 0
        gun_ici_sat_puani = 0
        gun_ici_karar_nedenleri = []
        gun_ici_riskler = []

        # VWAP
        if fiyat > seans_vwap:
            gun_ici_al_puani += 18
            gun_ici_karar_nedenleri.append("Fiyat seans VWAP uzerinde")
        elif fiyat < seans_vwap:
            gun_ici_sat_puani += 18
            gun_ici_riskler.append("Fiyat seans VWAP altinda")

        # MACD / histogram
        if macd5 > signal5:
            gun_ici_al_puani += 15
            gun_ici_karar_nedenleri.append("5dk MACD pozitif")
        else:
            gun_ici_sat_puani += 15
            gun_ici_riskler.append("5dk MACD negatif")

        if hist5 > 0 and hist5 > hist_onceki:
            gun_ici_al_puani += 12
            gun_ici_karar_nedenleri.append("Momentum gucleniyor")
        elif hist5 < 0 and hist5 < hist_onceki:
            gun_ici_sat_puani += 12
            gun_ici_riskler.append("Momentum zayifliyor")

        # MADDE 33 - KISA EMA TRENDI
        if fiyat > ema9_5 and ema9_5 > ema21_5:
            gun_ici_al_puani += 12
            gun_ici_karar_nedenleri.append("EMA9/EMA21 kisa trend pozitif")
        elif fiyat < ema9_5 and ema9_5 < ema21_5:
            gun_ici_sat_puani += 12
            gun_ici_riskler.append("EMA9/EMA21 kisa trend negatif")
        elif ema9_5 > ema21_5:
            gun_ici_al_puani += 5
            gun_ici_karar_nedenleri.append("EMA9 EMA21 uzerinde")
        elif ema9_5 < ema21_5:
            gun_ici_sat_puani += 5
            gun_ici_riskler.append("EMA9 EMA21 altinda")

        # MADDE 33 - OBV HACIM YONU
        if obv_durum == "YUKSELEN":
            gun_ici_al_puani += 8
            gun_ici_karar_nedenleri.append("OBV yukseliyor")
        elif obv_durum == "DUSEN":
            gun_ici_sat_puani += 8
            gun_ici_riskler.append("OBV dusuyor")

        # RSI
        if 50 <= rsi5 <= 68:
            gun_ici_al_puani += 12
            gun_ici_karar_nedenleri.append("RSI pozitif bolgede")
        elif rsi5 >= 75:
            gun_ici_sat_puani += 12
            gun_ici_riskler.append("RSI yuksek")
        elif rsi5 < 35:
            gun_ici_sat_puani += 8
            gun_ici_riskler.append("RSI zayif")

        # Hacim
        if hacim3_orani >= 150:
            gun_ici_al_puani += 15
            gun_ici_karar_nedenleri.append("Guclu gun ici hacim")
        elif hacim3_orani >= 120:
            gun_ici_al_puani += 9
        elif hacim3_orani < 60:
            gun_ici_sat_puani += 10
            gun_ici_riskler.append("Gun ici hacim zayif")

        # Kisa momentum
        if momentum15 > 0 and momentum30 > 0:
            gun_ici_al_puani += 12
            gun_ici_karar_nedenleri.append("15/30dk momentum pozitif")
        elif momentum15 < 0 and momentum30 < 0:
            gun_ici_sat_puani += 12
            gun_ici_riskler.append("15/30dk momentum negatif")

        # Kirilim
        if hacimli_kirilim:
            gun_ici_al_puani += 16
            gun_ici_karar_nedenleri.append("Hacimli kirilim")
        elif kirilim:
            gun_ici_al_puani += 7

        # Gun ici asiri hareket riski
        if acilisa_gore_degisim > 6:
            gun_ici_sat_puani += 10
            gun_ici_riskler.append("Gun ici yukselis fazla hizli")

        if zirveye_uzaklik > 4:
            gun_ici_sat_puani += 6
            gun_ici_riskler.append("Gun ici zirveden uzak")

        gun_ici_al_puani = max(
            0, min(100, gun_ici_al_puani)
        )
        gun_ici_sat_puani = max(
            0, min(100, gun_ici_sat_puani)
        )

        # =================================================
        # MADDE 44-47
        # GUN ICI DINAMIK HABER ETKILI AI MOTORU
        # =================================================
        gun_ici_haber_ai_aktif = False
        gun_ici_haber_ai_karar = "IZLE"
        gun_ici_haber_fiyat_teyidi = 0.0
        gun_ici_nihai_ai_puan = float(gun_ici_al_puani)
        gun_ici_haber_seviye_etkisi = 0.0

        try:
            makro_canli = canli_makro_puani_getir(
                sembol
            )

            makro_ai_puani = guvenli_float(
                makro_canli.get("makro_puani")
            )

            sektor_ai_puani = guvenli_float(
                makro_canli.get("sektor_puani")
            )

            gun_ici_haber_ai_aktif = (
                (
                    abs(float(haber_puani or 0)) >= 0.5
                    and float(haber_guven or 0) >= 25
                )
                or abs(makro_ai_puani) >= 0.5
                or abs(sektor_ai_puani) >= 0.5
            )

            if gun_ici_haber_ai_aktif:

                vwap_ai_ustu = (
                    True
                    if fiyat > seans_vwap
                    else False
                )

                obv_ai_pozitif = None

                if obv_durum == "YUKSELEN":
                    obv_ai_pozitif = True
                elif obv_durum == "DUSEN":
                    obv_ai_pozitif = False

                # 5dk ATR varsa onu kullan.
                # Aşırı küçük ATR durumunda gün içi aralık koruma sağlar.
                ai_atr = max(
                    float(atr14_5 or 0),
                    float(gun_aralik or 0) * 0.20,
                    fiyat * 0.002
                )

                ai_sonuc = (
                    haber_etki_motoru.hisse_haber_ai_guncelle(
                        teknik_puan=gun_ici_al_puani,
                        fiyat=fiyat,
                        atr=ai_atr,
                        destek=gun_dusuk,
                        direnc=max(
                            yakin_direnc,
                            gun_yuksek
                        ),
                        haber_puani=haber_puani,
                        haber_guven=haber_guven,
                        sektor_puani=canli_makro_puani_getir(sembol).get(
                            "sektor_puani",
                            0
                        ),
                        makro_puani=canli_makro_puani_getir(sembol).get(
                            "makro_puani",
                            0
                        ),
                        fiyat_degisim_yuzde=acilisa_gore_degisim,
                        hacim_orani=hacim3_orani,
                        vwap_ustu=vwap_ai_ustu,
                        obv_pozitif=obv_ai_pozitif,
                        piyasa_rejimi=0,
                        haber_dakika=0,
                        ogrenilmis_katsayi=1.0,
                    )
                )

                gun_ici_haber_ai_karar = ai_sonuc.get(
                    "ai_karar",
                    "IZLE"
                )

                gun_ici_haber_fiyat_teyidi = float(
                    ai_sonuc.get(
                        "fiyat_teyidi",
                        0
                    ) or 0
                )

                gun_ici_nihai_ai_puan = float(
                    ai_sonuc.get(
                        "nihai_ai_puan",
                        gun_ici_al_puani
                    ) or gun_ici_al_puani
                )

                gun_ici_haber_seviye_etkisi = float(
                    ai_sonuc.get(
                        "haber_seviye_etkisi",
                        0
                    ) or 0
                )

                # Haber etkisine göre gün içi seviyeleri güncelle.
                alim_alt = float(
                    ai_sonuc.get(
                        "alim_alt",
                        alim_alt
                    )
                )

                alim_ust = float(
                    ai_sonuc.get(
                        "alim_ust",
                        alim_ust
                    )
                )

                kar_al = float(
                    ai_sonuc.get(
                        "hedef",
                        kar_al
                    )
                )

                stop = float(
                    ai_sonuc.get(
                        "stop",
                        stop
                    )
                )

                gun_ici_karar_nedenleri.append(
                    f"Haber AI {float(haber_puani):+.1f}/10 "
                    f"| Guven %{float(haber_guven):.0f} "
                    f"| Nihai AI {gun_ici_nihai_ai_puan:.1f}"
                )

        except Exception as gun_ici_ai_hata:
            gun_ici_haber_ai_aktif = False

        gun_ici_risk = max(
            0,
            ((fiyat - stop) / fiyat) * 100
        )

        gun_ici_getiri = max(
            0,
            ((kar_al - fiyat) / fiyat) * 100
        )

        gun_ici_rr = (
            gun_ici_getiri / gun_ici_risk
            if gun_ici_risk > 0
            else 0
        )

        gun_ici_guven = max(
            gun_ici_al_puani,
            gun_ici_sat_puani
        )

        if (
            gun_ici_al_puani >= 65
            and gun_ici_al_puani >= gun_ici_sat_puani + 20
            and gun_ici_rr >= 1.40
        ):
            gun_ici_karar = "AL"

        elif (
            gun_ici_sat_puani >= 60
            and gun_ici_sat_puani >= gun_ici_al_puani + 20
        ):
            gun_ici_karar = "SAT"

        else:
            gun_ici_karar = "IZLE"

        # Haber AI yalnız anlamlı haber olduğunda nihai karara müdahale eder.
        if gun_ici_haber_ai_aktif:

            if gun_ici_haber_ai_karar == "GUCLU_AL_ADAYI":
                # Çok güçlü teknik SAT varsa tek haberle tersine çevirmiyoruz.
                if gun_ici_sat_puani < 75:
                    gun_ici_karar = "AL"

            elif gun_ici_haber_ai_karar == "AL":
                if gun_ici_sat_puani < 70:
                    gun_ici_karar = "AL"

            elif gun_ici_haber_ai_karar == "SAT":
                gun_ici_karar = "SAT"

            elif gun_ici_haber_ai_karar == "RISKLI_IZLE":
                if gun_ici_karar == "AL":
                    gun_ici_karar = "IZLE"

        gun_ici_ana_neden = (
            gun_ici_karar_nedenleri[0]
            if gun_ici_karar_nedenleri
            else "Net pozitif teyit yok"
        )

        gun_ici_ana_risk = (
            gun_ici_riskler[0]
            if gun_ici_riskler
            else "Belirgin ana risk yok"
        )

        # Hacimli kirilim seviyesi.
        hacimli_kirilim_seviyesi = max(
            yakin_direnc,
            gun_yuksek
        )

        # Kirilim sonrasi ilk hedef.
        kirilim_sonrasi_hedef = (
            hacimli_kirilim_seviyesi
            + (gun_aralik * 0.45)
        )

        if hacimli_kirilim:
            kirilim_durumu = "HACIMLI KIRILIM VAR"
        elif kirilim:
            kirilim_durumu = "DIRENC KIRILDI - HACIM TEYIDI BEKLENIYOR"
        else:
            kirilim_durumu = "HACIMLI KIRILIM BEKLENIYOR"

        return {
            "sembol": sembol,
            "fiyat": fiyat,
            "gun_ici_puan": puan,
            "teknik_gun_ici_puan": teknik_gun_ici_puan,
            "haber_puani": haber_puani,
            "haber_guven": haber_guven,
            "haber_sinifi": haber_sinifi,

            # MADDE 44-47 - GUN ICI HABER AI
            "gun_ici_haber_ai_aktif": gun_ici_haber_ai_aktif,
            "gun_ici_haber_ai_karar": gun_ici_haber_ai_karar,
            "gun_ici_haber_fiyat_teyidi": round(
                gun_ici_haber_fiyat_teyidi,
                2
            ),
            "gun_ici_nihai_ai_puan": round(
                gun_ici_nihai_ai_puan,
                1
            ),
            "gun_ici_haber_seviye_etkisi": round(
                gun_ici_haber_seviye_etkisi,
                3
            ),
            "makro_puani": canli_makro_puani_getir(sembol).get(
                "makro_puani",
                0
            ),
            "sektor_puani": canli_makro_puani_getir(sembol).get(
                "sektor_puani",
                0
            ),
            "makro_sektor": canli_makro_puani_getir(sembol).get(
                "sektor",
                ""
            ),

            "gun_ici_karar": gun_ici_karar,
            "gun_ici_guven": gun_ici_guven,
            "gun_ici_al_puani": gun_ici_al_puani,
            "gun_ici_sat_puani": gun_ici_sat_puani,
            "gun_ici_risk": round(gun_ici_risk, 2),
            "gun_ici_getiri": round(gun_ici_getiri, 2),
            "gun_ici_rr": round(gun_ici_rr, 2),
            "gun_ici_ana_neden": gun_ici_ana_neden,
            "gun_ici_ana_risk": gun_ici_ana_risk,
            "seans_vwap": round(seans_vwap, 2),
            "seans_vwap_uzaklik": round(seans_vwap_uzaklik, 2),
            "acilisa_gore_degisim": acilisa_gore_degisim,
            "dipten_toparlanma": dipten_toparlanma,
            "zirveye_uzaklik": zirveye_uzaklik,
            "rsi5": rsi5,
            "macd5": macd5,
            "signal5": signal5,
            "hist5": hist5,
            "hist_onceki": hist_onceki,

            # MADDE 33 - GUN ICI EK GOSTERGELER
            "ema9_5": round(ema9_5, 4),
            "ema21_5": round(ema21_5, 4),
            "ema_fark_yuzde": round(ema_fark_yuzde, 2),
            "obv5": round(obv5, 2),
            "obv_degisim_15dk": round(obv_degisim_15dk, 2),
            "obv_durum": obv_durum,
            "atr14_5": round(atr14_5, 4),
            "atr14_5_yuzde": round(atr14_5_yuzde, 2),
            "oynaklik_durumu": oynaklik_durumu,

            "hacim_hizlanma": hacim_hizlanma,
            "hacim3_orani": hacim3_orani,
            "momentum15": momentum15,
            "momentum30": momentum30,
            "gun_yuksek": gun_yuksek,
            "gun_dusuk": gun_dusuk,
            "yakin_direnc": yakin_direnc,
            "kirilim": bool(kirilim),
            "hacimli_kirilim": bool(hacimli_kirilim),
            "gun_ici_alim_alt": round(alim_alt, 2),
            "gun_ici_alim_ust": round(alim_ust, 2),
            "gun_ici_kar_al": round(kar_al, 2),
            "gun_ici_stop": round(stop, 2),
            "gun_ici_hacimli_kirilim": round(hacimli_kirilim_seviyesi, 2),
            "gun_ici_kirilim_hedef": round(kirilim_sonrasi_hedef, 2),
            "gun_ici_kirilim_durumu": kirilim_durumu,
            "nedenler": nedenler,
            "veri_tarihi": str(veri.index[-1])
        }

    except Exception as e:
        hata = str(e).lower()

        if "invalid symbol" in hata:
            return {
                "_durum": "GECERSIZ_SEMBOL",
                "sembol": sembol
            }

        return {
            "_durum": "GECICI_HATA",
            "sembol": sembol,
            "_hata": str(e)
        }


def gun_ici_sinyal_durumlarini_guncelle(sonuclar):
    """
    Yeni gun ici taramayi onceki gun_ici_tum.json ile karsilastirir.
    Sinyal durumu, baslangic zamani ve sinyal yasini ekler.
    """
    import json
    import os
    from datetime import datetime

    onceki_map = {}

    dosya = os.path.join(
        os.path.dirname(__file__),
        "webapp",
        "data",
        "gun_ici_tum.json"
    )

    try:
        if os.path.exists(dosya):
            with open(dosya, "r", encoding="utf-8") as f:
                eski = json.load(f)

            for x in eski.get("hisseler", []):
                sembol = str(x.get("sembol", "")).upper().strip()
                if sembol:
                    onceki_map[sembol] = x

    except Exception as e:
        print("SINYAL GECMISI OKUMA UYARISI:", e)

    simdi = datetime.now()

    for x in sonuclar:
        sembol = str(x.get("sembol", "")).upper().strip()
        karar = str(x.get("gun_ici_karar", "IZLE")).upper()

        onceki = onceki_map.get(sembol, {})
        onceki_karar = str(
            onceki.get("gun_ici_karar", "IZLE")
        ).upper()

        onceki_durum = str(
            onceki.get("gun_ici_sinyal_durumu", "")
        ).upper()

        onceki_baslangic = onceki.get(
            "gun_ici_sinyal_baslangic"
        )

        baslangic = None

        if karar == "AL":
            if onceki_karar == "AL":
                durum = "AL DEVAM"
                baslangic = onceki_baslangic
            else:
                durum = "YENI AL"

        elif karar == "SAT":
            if onceki_karar == "SAT":
                durum = "SAT DEVAM"
                baslangic = onceki_baslangic

            elif (
                onceki_karar == "AL"
                or onceki_durum in ("YENI AL", "AL DEVAM", "ZAYIFLIYOR")
            ):
                durum = "SAT'A DONDU"
                baslangic = onceki_baslangic

            else:
                durum = "YENI SAT"

        else:
            if (
                onceki_karar == "AL"
                or onceki_durum in ("YENI AL", "AL DEVAM")
            ):
                durum = "ZAYIFLIYOR"
                baslangic = onceki_baslangic
            else:
                durum = "IZLE"

        # Yeni AL/SAT sinyalinde baslangic zamani simdidir.
        if durum in ("YENI AL", "YENI SAT"):
            baslangic = simdi.strftime("%Y-%m-%d %H:%M:%S")

        # Devam eden sinyalde eski baslangic yoksa simdiyi kullan.
        if durum in (
            "AL DEVAM",
            "SAT DEVAM",
            "ZAYIFLIYOR",
            "SAT'A DONDU"
        ) and not baslangic:
            baslangic = simdi.strftime("%Y-%m-%d %H:%M:%S")

        yas_dk = 0

        if baslangic:
            try:
                dt = datetime.strptime(
                    str(baslangic),
                    "%Y-%m-%d %H:%M:%S"
                )

                yas_dk = max(
                    0,
                    int((simdi - dt).total_seconds() / 60)
                )

            except Exception:
                yas_dk = 0

        x["gun_ici_sinyal_durumu"] = durum
        x["gun_ici_sinyal_baslangic"] = baslangic
        x["gun_ici_sinyal_yasi_dk"] = yas_dk

    return sonuclar



# =========================================================
# AI OGRENME MOTORU V1
# Tum BIST sinyallerinden ornek toplar.
# Modeller birbirinden ayri tutulur.
# =========================================================

def ai_ogrenme_kaydet(sonuclar, model="GUN_ICI"):
    import json
    import os
    from datetime import datetime

    if not sonuclar:
        return 0

    klasor = os.path.join(
        os.path.dirname(__file__),
        "webapp",
        "data"
    )
    os.makedirs(klasor, exist_ok=True)

    dosya = os.path.join(klasor, "ai_ogrenme_gecmisi.json")

    if os.path.exists(dosya):
        try:
            with open(dosya, "r", encoding="utf-8") as f:
                veri = json.load(f)
        except Exception:
            veri = {"kayitlar": []}
    else:
        veri = {"kayitlar": []}

    kayitlar = veri.get("kayitlar", [])
    mevcut = {
        str(x.get("kayit_id"))
        for x in kayitlar
        if x.get("kayit_id")
    }

    simdi = datetime.now()
    zaman = simdi.strftime("%Y-%m-%d %H:%M:%S")
    dakika = (simdi.minute // 5) * 5

    # AI EGITIM KORUMASI
    # Sadece hafta ici BIST seansi icinde olusan kayitlar
    # gercek egitim verisi sayilir.
    hafta_ici = simdi.weekday() < 5
    dakika_no = simdi.hour * 60 + simdi.minute
    seans_acik = (
        hafta_ici
        and (10 * 60) <= dakika_no <= (18 * 60 + 10)
    )

    egitim_durumu = (
        "EGITIM"
        if seans_acik
        else "REFERANS"
    )

    eklenen = 0

    for a in sonuclar:
        sembol = str(a.get("sembol", "")).upper().strip()
        karar = str(a.get("gun_ici_karar", "IZLE")).upper()

        if not sembol:
            continue

        # IZLE dahil tum analizler veri olarak saklanir.
        # Basari istatistiginde AL/SAT sinyalleri esas alinacak.
        kayit_id = (
            f"{model}_{sembol}_"
            f"{simdi.strftime('%Y%m%d_%H')}{dakika:02d}"
        )

        if kayit_id in mevcut:
            continue

        fiyat = float(a.get("fiyat", 0) or 0)

        kayit = {
            "kayit_id": kayit_id,
            "model": model,
            "sembol": sembol,
            "zaman": zaman,
            "egitim_durumu": egitim_durumu,

            "karar": karar,
            "sinyal_durumu": a.get(
                "gun_ici_sinyal_durumu",
                karar
            ),

            "fiyat": fiyat,
            "hedef": float(
                a.get("gun_ici_kar_al", 0) or 0
            ),
            "stop": float(
                a.get("gun_ici_stop", 0) or 0
            ),

            "teknik_puan": float(
                a.get("gun_ici_puan", 0) or 0
            ),
            "guven": float(
                a.get("gun_ici_guven", 0) or 0
            ),
            "al_puani": float(
                a.get("gun_ici_al_puani", 0) or 0
            ),
            "sat_puani": float(
                a.get("gun_ici_sat_puani", 0) or 0
            ),
            "rr": float(
                a.get("gun_ici_rr", 0) or 0
            ),

            "rsi5": float(
                a.get("rsi5", 0) or 0
            ),
            "seans_vwap": float(
                a.get("seans_vwap", 0) or 0
            ),
            "vwap_uzaklik": float(
                a.get("seans_vwap_uzaklik", 0) or 0
            ),

            "ema9": float(
                a.get("ema9_5", 0) or 0
            ),
            "ema21": float(
                a.get("ema21_5", 0) or 0
            ),
            "ema_fark": float(
                a.get("ema_fark_yuzde", 0) or 0
            ),

            "obv_durum": a.get(
                "obv_durum",
                "YATAY"
            ),
            "obv_degisim": float(
                a.get("obv_degisim_15dk", 0) or 0
            ),

            "atr_yuzde": float(
                a.get("atr14_5_yuzde", 0) or 0
            ),
            "oynaklik": a.get(
                "oynaklik_durumu",
                ""
            ),

            "hacim_orani": float(
                a.get("hacim3_orani", 0) or 0
            ),
            "momentum15": float(
                a.get("momentum15", 0) or 0
            ),
            "momentum30": float(
                a.get("momentum30", 0) or 0
            ),

            "hacimli_kirilim": bool(
                a.get("hacimli_kirilim", False)
            ),

            # Seans disi kayitlar sadece referans veridir.
            # Gercek basari / ogrenme hesabina girmez.
            "sonuc": (
                "BEKLIYOR"
                if egitim_durumu == "EGITIM"
                else "REFERANS"
            ),
            "sonuc_fiyat": None,
            "sonuc_zaman": None,
            "getiri_yuzde": None,
            "hedef_vurdu": False,
            "stop_vurdu": False
        }

        kayitlar.append(kayit)
        mevcut.add(kayit_id)
        eklenen += 1

    # Dosyanin kontrolsuz buyumesini engelle.
    # Son 100.000 ornek korunur.
    if len(kayitlar) > 100000:
        kayitlar = kayitlar[-100000:]

    veri = {
        "guncelleme": zaman,
        "toplam_kayit": len(kayitlar),
        "kayitlar": kayitlar
    }

    with open(dosya, "w", encoding="utf-8") as f:
        json.dump(
            veri,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"AI OGRENME | MODEL: {model} | "
        f"YENI ORNEK: {eklenen} | "
        f"TOPLAM: {len(kayitlar)}"
    )

    return eklenen


def ai_ogrenme_ozeti_yaz():
    import json
    import os
    from datetime import datetime
    from collections import Counter

    klasor = os.path.join(
        os.path.dirname(__file__),
        "webapp",
        "data"
    )

    kaynak = os.path.join(
        klasor,
        "ai_ogrenme_gecmisi.json"
    )
    hedef = os.path.join(
        klasor,
        "ai_ogrenme_ozeti.json"
    )

    if not os.path.exists(kaynak):
        return

    try:
        with open(kaynak, "r", encoding="utf-8") as f:
            veri = json.load(f)
    except Exception:
        return

    kayitlar = veri.get("kayitlar", [])

    modeller = Counter(
        str(x.get("model", "BILINMIYOR"))
        for x in kayitlar
    )
    kararlar = Counter(
        str(x.get("karar", "IZLE"))
        for x in kayitlar
    )
    sonuclar = Counter(
        str(x.get("sonuc", "BEKLIYOR"))
        for x in kayitlar
    )

    # REFERANS kayitlar sadece ham veri olarak tutulur.
    # AI basari/ogrenme hesabina dahil edilmez.
    tamamlanan = [
        x for x in kayitlar
        if x.get("sonuc") not in (
            None,
            "",
            "BEKLIYOR",
            "REFERANS"
        )
        and x.get("egitim_durumu") != "REFERANS"
    ]

    basarili = [
        x for x in tamamlanan
        if x.get("sonuc") == "BASARILI"
    ]

    if tamamlanan:
        basari = (
            len(basarili) /
            len(tamamlanan)
        ) * 100.0
    else:
        basari = 0.0

    ozet = {
        "guncelleme": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "durum": "OGRENIYOR",
        "toplam_ornek": len(kayitlar),
        "tamamlanan_ornek": len(tamamlanan),
        "bekleyen_ornek": sonuclar.get(
            "BEKLIYOR",
            0
        ),
        "basarili_ornek": len(basarili),
        "basari_yuzde": round(basari, 2),
        "modeller": dict(modeller),
        "kararlar": dict(kararlar),
        "minimum_ogrenme_ornegi": 30,
        "not": (
            "Sistem veri topluyor. "
            "Yeterli tamamlanmis ornekten sonra "
            "gosterge ve kombinasyon agirliklari "
            "hesaplanacak."
        )
    }

    with open(hedef, "w", encoding="utf-8") as f:
        json.dump(
            ozet,
            f,
            ensure_ascii=False,
            indent=2
        )





def ai_ogrenilmis_agirliklari_hesapla():
    """
    Tamamlanmis gercek GUN_ICI AL/SAT sinyallerinden
    gosterge ve kombinasyon basarilarini hesaplar.

    REFERANS kayitlar kullanilmaz.
    Minimum 30 tamamlanmis sinyal olmadan
    aktif ogrenilmis agirlik uretilmez.
    """
    import json
    import os
    from datetime import datetime
    from collections import defaultdict

    klasor = os.path.join(
        os.path.dirname(__file__),
        "webapp",
        "data"
    )

    kaynak = os.path.join(
        klasor,
        "ai_ogrenme_gecmisi.json"
    )

    hedef = os.path.join(
        klasor,
        "ai_ogrenilmis_agirliklar.json"
    )

    if not os.path.exists(kaynak):
        return None

    try:
        with open(kaynak, "r", encoding="utf-8") as f:
            veri = json.load(f)
    except Exception:
        return None

    kayitlar = [
        x for x in veri.get("kayitlar", [])
        if x.get("model") == "GUN_ICI"
        and x.get("egitim_durumu") != "REFERANS"
        and x.get("karar") in ("AL", "SAT")
        and x.get("sonuc") in (
            "BASARILI",
            "BASARISIZ"
        )
    ]

    minimum = 30

    if len(kayitlar) < minimum:
        sonuc = {
            "guncelleme": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "durum": "VERI_TOPLANIYOR",
            "tamamlanan_sinyal": len(kayitlar),
            "minimum_gerekli": minimum,
            "kalan": max(
                0,
                minimum - len(kayitlar)
            ),
            "aktif": False,
            "gostergeler": {},
            "not": (
                "Minimum gercek tamamlanmis AL/SAT "
                "ornegi olusmadan ogrenilmis agirliklar "
                "karar motoruna uygulanmaz."
            )
        }

        with open(hedef, "w", encoding="utf-8") as f:
            json.dump(
                sonuc,
                f,
                ensure_ascii=False,
                indent=2
            )

        return sonuc

    istatistik = defaultdict(
        lambda: {
            "ornek": 0,
            "basarili": 0
        }
    )

    def ekle(anahtar, basarili):
        istatistik[anahtar]["ornek"] += 1
        if basarili:
            istatistik[anahtar]["basarili"] += 1

    for x in kayitlar:
        basarili = (
            x.get("sonuc") == "BASARILI"
        )

        karar = x.get("karar")

        vwap = float(
            x.get("vwap_uzaklik", 0) or 0
        )
        ema = float(
            x.get("ema_fark", 0) or 0
        )
        rsi = float(
            x.get("rsi5", 0) or 0
        )
        hacim = float(
            x.get("hacim_orani", 0) or 0
        )
        mom15 = float(
            x.get("momentum15", 0) or 0
        )
        mom30 = float(
            x.get("momentum30", 0) or 0
        )
        rr = float(
            x.get("rr", 0) or 0
        )

        obv = str(
            x.get("obv_durum", "YATAY")
        ).upper()

        kirilim = bool(
            x.get("hacimli_kirilim", False)
        )

        # VWAP
        if vwap > 0:
            ekle(
                f"{karar}|VWAP_USTU",
                basarili
            )
        elif vwap < 0:
            ekle(
                f"{karar}|VWAP_ALTI",
                basarili
            )

        # EMA 9 / 21
        if ema > 0:
            ekle(
                f"{karar}|EMA_POZITIF",
                basarili
            )
        elif ema < 0:
            ekle(
                f"{karar}|EMA_NEGATIF",
                basarili
            )

        # OBV
        ekle(
            f"{karar}|OBV_{obv}",
            basarili
        )

        # RSI
        if rsi < 35:
            rsi_grup = "RSI_DUSUK"
        elif rsi < 50:
            rsi_grup = "RSI_35_50"
        elif rsi <= 68:
            rsi_grup = "RSI_50_68"
        elif rsi < 75:
            rsi_grup = "RSI_68_75"
        else:
            rsi_grup = "RSI_YUKSEK"

        ekle(
            f"{karar}|{rsi_grup}",
            basarili
        )

        # HACIM
        if hacim >= 150:
            hacim_grup = "HACIM_150_USTU"
        elif hacim >= 120:
            hacim_grup = "HACIM_120_150"
        elif hacim >= 80:
            hacim_grup = "HACIM_NORMAL"
        else:
            hacim_grup = "HACIM_ZAYIF"

        ekle(
            f"{karar}|{hacim_grup}",
            basarili
        )

        # MOMENTUM
        if mom15 > 0 and mom30 > 0:
            momentum = "MOMENTUM_POZITIF"
        elif mom15 < 0 and mom30 < 0:
            momentum = "MOMENTUM_NEGATIF"
        else:
            momentum = "MOMENTUM_KARISIK"

        ekle(
            f"{karar}|{momentum}",
            basarili
        )

        # HACIMLI KIRILIM
        ekle(
            f"{karar}|KIRILIM_"
            + ("VAR" if kirilim else "YOK"),
            basarili
        )

        # R/R
        if rr >= 2:
            rr_grup = "RR_2_USTU"
        elif rr >= 1.4:
            rr_grup = "RR_1_4_2"
        else:
            rr_grup = "RR_DUSUK"

        ekle(
            f"{karar}|{rr_grup}",
            basarili
        )

        # Ana kombinasyon
        if karar == "AL":
            kombinasyon = (
                vwap > 0
                and ema > 0
                and obv == "YUKSELEN"
                and mom15 > 0
                and mom30 > 0
            )
        else:
            kombinasyon = (
                vwap < 0
                and ema < 0
                and obv == "DUSEN"
                and mom15 < 0
                and mom30 < 0
            )

        if kombinasyon:
            ekle(
                f"{karar}|ANA_KOMBINASYON",
                basarili
            )

    gostergeler = {}

    for anahtar, d in istatistik.items():
        n = d["ornek"]
        bas = d["basarili"]

        oran = (
            (bas / n) * 100.0
            if n
            else 0.0
        )

        # Tek tek kriterlerin algoritmaya etkisi icin
        # kendi minimum ornek korumasi.
        guvenilir = n >= 30

        # 50% notr merkezdir.
        # Maksimum +/-15 puanlik ogrenilmis etki.
        if guvenilir:
            agirlik = max(
                -15.0,
                min(
                    15.0,
                    (oran - 50.0) * 0.30
                )
            )
        else:
            agirlik = 0.0

        gostergeler[anahtar] = {
            "ornek": n,
            "basarili": bas,
            "basari_yuzde": round(
                oran,
                2
            ),
            "guvenilir": guvenilir,
            "ogrenilmis_agirlik": round(
                agirlik,
                2
            )
        }

    genel_basari = sum(
        1
        for x in kayitlar
        if x.get("sonuc") == "BASARILI"
    )

    sonuc = {
        "guncelleme": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "durum": "AKTIF",
        "aktif": True,
        "tamamlanan_sinyal": len(kayitlar),
        "minimum_gerekli": minimum,
        "genel_basari_yuzde": round(
            (
                genel_basari /
                len(kayitlar)
            ) * 100.0,
            2
        ),
        "gostergeler": gostergeler,
        "not": (
            "Ogrenilmis agirliklar teknik motorun "
            "yerine gecmez. Ikinci guven katmani "
            "olarak kullanilir."
        )
    }

    with open(hedef, "w", encoding="utf-8") as f:
        json.dump(
            sonuc,
            f,
            ensure_ascii=False,
            indent=2
        )

    return sonuc



def ai_sinyal_sonuc_guncelle(guncel_sonuclar):
    """
    GUN_ICI modelindeki gercek AL/SAT sinyallerini degerlendirir.

    REFERANS kayitlar egitime girmez.
    IZLE kayitlari basari hesabina girmez.

    AL:
      hedefe ulasmak = BASARILI
      stopa dusmek   = BASARISIZ

    SAT:
      stop seviyesi altina gerilemek = BASARILI
      hedef seviyesi ustune cikmak   = BASARISIZ

    Acik sinyal hedef/stop olmadan devam ediyorsa BEKLIYOR kalir.
    """
    import json
    import os
    from datetime import datetime

    klasor = os.path.join(
        os.path.dirname(__file__),
        "webapp",
        "data"
    )

    dosya = os.path.join(
        klasor,
        "ai_ogrenme_gecmisi.json"
    )

    if not os.path.exists(dosya):
        return 0

    try:
        with open(dosya, "r", encoding="utf-8") as f:
            veri = json.load(f)
    except Exception as e:
        print("AI SONUC OKUMA HATASI:", e)
        return 0

    guncel_map = {}

    for a in (guncel_sonuclar or []):
        sembol = str(
            a.get("sembol", "")
        ).upper().strip()

        if sembol:
            guncel_map[sembol] = a

    simdi = datetime.now()
    degisen = 0

    for kayit in veri.get("kayitlar", []):

        if kayit.get("model") != "GUN_ICI":
            continue

        if kayit.get("egitim_durumu") == "REFERANS":
            continue

        if kayit.get("sonuc") != "BEKLIYOR":
            continue

        karar = str(
            kayit.get("karar", "")
        ).upper()

        if karar not in ("AL", "SAT"):
            continue

        sembol = str(
            kayit.get("sembol", "")
        ).upper()

        guncel = guncel_map.get(sembol)

        if not guncel:
            continue

        giris = float(
            kayit.get("fiyat", 0) or 0
        )
        hedef = float(
            kayit.get("hedef", 0) or 0
        )
        stop = float(
            kayit.get("stop", 0) or 0
        )
        fiyat = float(
            guncel.get("fiyat", 0) or 0
        )

        if giris <= 0 or fiyat <= 0:
            continue

        # AL sinyalinde yukari hareket pozitiftir.
        if karar == "AL":
            getiri = (
                (fiyat - giris) /
                giris
            ) * 100.0

            if hedef > 0 and fiyat >= hedef:
                sonuc = "BASARILI"
                kayit["hedef_vurdu"] = True

            elif stop > 0 and fiyat <= stop:
                sonuc = "BASARISIZ"
                kayit["stop_vurdu"] = True

            else:
                continue

        # SAT sinyalinde asagi hareket pozitiftir.
        else:
            getiri = (
                (giris - fiyat) /
                giris
            ) * 100.0

            # Mevcut gun ici seviyeler long mantiginda
            # tutuldugu icin SAT icin ters yonlu
            # esik giris fiyatina gore hesaplanir.
            hedef_mesafe = (
                abs(hedef - giris)
                if hedef > 0
                else giris * 0.02
            )

            stop_mesafe = (
                abs(giris - stop)
                if stop > 0
                else giris * 0.015
            )

            sat_hedef = max(
                0.01,
                giris - hedef_mesafe
            )

            sat_stop = (
                giris + stop_mesafe
            )

            kayit["sat_hedef"] = round(
                sat_hedef,
                4
            )
            kayit["sat_stop"] = round(
                sat_stop,
                4
            )

            if fiyat <= sat_hedef:
                sonuc = "BASARILI"
                kayit["hedef_vurdu"] = True

            elif fiyat >= sat_stop:
                sonuc = "BASARISIZ"
                kayit["stop_vurdu"] = True

            else:
                continue

        kayit["sonuc"] = sonuc
        kayit["egitim_durumu"] = "TAMAMLANDI"
        kayit["sonuc_fiyat"] = round(
            fiyat,
            4
        )
        kayit["sonuc_zaman"] = simdi.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        kayit["getiri_yuzde"] = round(
            getiri,
            2
        )

        degisen += 1

    with open(dosya, "w", encoding="utf-8") as f:
        json.dump(
            veri,
            f,
            ensure_ascii=False,
            indent=2
        )

    if degisen:
        print(
            "AI SONUC | TAMAMLANAN YENI SINYAL:",
            degisen
        )

    return degisen



def gun_ici_top10_tara():
    """Tum BIST hisselerini hizli Stream mimarisiyle 5 dk veride tarar."""
    tum_semboller = bist_hisseleri_getir()
    toplam = len(tum_semboller)

    bilinen_gecersiz = gun_ici_gecersiz_oku()
    semboller = [s for s in tum_semboller if s not in bilinen_gecersiz]

    print(f"ONBELLEK: {len(bilinen_gecersiz)} gecersiz sembol atlandi")
    print(f"GUN ICI STREAM TARAMA BASLADI: {toplam} hisse | TARANACAK: {len(semboller)}")

    normal_map = {}
    filtre_disi_map = {}
    gecersiz_map = {}
    gecici_hata_map = {}

    veri_map, stream_basarisiz = gun_ici_stream_verileri_getir(
        semboller,
        paket_boyutu=100,
        bekleme=10
    )

    # Stream ile gelen verilerin analizi artik tamamen yerel ve cok hizlidir.
    for i, sembol in enumerate(semboller, start=1):
        if sembol not in veri_map:
            continue

        analiz = gun_ici_analiz_hesapla(sembol, veri_map[sembol])
        if analiz is None:
            gecici_hata_map[sembol] = {
                "_durum": "GECICI_HATA", "sembol": sembol, "_hata": "BOS_SONUC"
            }
            continue

        durum = analiz.get("_durum", "NORMAL")
        if durum in ("FILTRE_DISI", "YETERSIZ_GUNICI_VERI"):
            filtre_disi_map[sembol] = analiz
        elif durum == "GECERSIZ_SEMBOL":
            gecersiz_map[sembol] = analiz
        elif durum == "GECICI_HATA":
            gecici_hata_map[sembol] = analiz
        else:
            normal_map[sembol] = analiz

        if i % 100 == 0:
            print(f"YEREL ANALIZ: {i}/{len(semboller)}")

    # Stream'de veri gelmeyen az sayida hisse olursa eski guvenilir yol ile tamamla.
    if stream_basarisiz:
        print(f"STREAM YEDEK TARAMA: {len(stream_basarisiz)} hisse")
        for sembol in stream_basarisiz:
            analiz = gun_ici_analiz_hesapla(sembol)
            if analiz is None:
                gecici_hata_map[sembol] = {
                    "_durum": "GECICI_HATA", "sembol": sembol, "_hata": "BOS_SONUC"
                }
                continue

            durum = analiz.get("_durum", "NORMAL")
            if durum in ("FILTRE_DISI", "YETERSIZ_GUNICI_VERI"):
                filtre_disi_map[sembol] = analiz
            elif durum == "GECERSIZ_SEMBOL":
                gecersiz_map[sembol] = analiz
            elif durum == "GECICI_HATA":
                gecici_hata_map[sembol] = analiz
            else:
                normal_map[sembol] = analiz
                gecici_hata_map.pop(sembol, None)

    sonuclar = list(normal_map.values())

    # MADDE 33 - SINYAL DURUMU VE SINYAL YASI
    sonuclar = gun_ici_sinyal_durumlarini_guncelle(sonuclar)

    # AI - ONCE ESKI GERCEK AL/SAT SINYALLERININ
    # SONUCLARINI GUNCEL FIYATLARLA DEGERLENDIR.
    ai_sinyal_sonuc_guncelle(sonuclar)

    # AI - SONRA BU TARAMADAKI TUM ANALIZLERI
    # YENI OGRENME ORNEGI OLARAK KAYDET.
    ai_ogrenme_kaydet(
        sonuclar,
        model="GUN_ICI"
    )

    # TELEFON / WEB ICIN AI OZETINI GUNCELLE.
    ai_ogrenme_ozeti_yaz()

    # TAMAMLANMIS GERCEK SINYALLERDEN
    # OGRENILMIS GOSTERGE AGIRLIKLARINI GUNCELLE.
    ai_ogrenilmis_agirliklari_hesapla()

    sonuclar.sort(
        key=lambda a: (
            guvenli_float(a.get("gun_ici_puan")),
            guvenli_float(a.get("hacim3_orani")),
            guvenli_float(a.get("momentum15"))
        ),
        reverse=True
    )

    top10 = [
        a for a in sonuclar
        if guvenli_float(a.get("gun_ici_puan")) >= 45
    ][:10]

    print(
        "GUN ICI OZET | "
        f"TOPLAM: {toplam} | ANALIZ: {len(normal_map)} | "
        f"FILTRE DISI: {len(filtre_disi_map)} | "
        f"GECERSIZ: {len(gecersiz_map)} | HATA: {len(gecici_hata_map)}"
    )

    if gecici_hata_map:
        print("KALAN HATALAR:", ", ".join(list(gecici_hata_map.keys())[:30]))

    yeni_gecersizler = bilinen_gecersiz.union(gecersiz_map.keys())
    gun_ici_gecersiz_yaz(yeni_gecersizler)
    print(f"ONBELLEK KAYDEDILDI: {len(yeni_gecersizler)} gecersiz sembol")

    # Gun Ici TOP 10 sonucunu web icin kaydet
    try:
        import json
        import os

        web_dosya = os.path.join(
            os.path.dirname(__file__),
            "webapp",
            "data",
            "gun_ici_top10.json"
        )

        os.makedirs(
            os.path.dirname(web_dosya),
            exist_ok=True
        )

        web_veri = {
            "guncelleme": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "toplam": toplam,
            "teknik_aday": len(sonuclar),
            "top10": top10
        }

        with open(web_dosya, "w", encoding="utf-8") as f:
            json.dump(
                web_veri,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )

        print(
            f"GUN ICI WEB VERISI KAYDEDILDI: {len(top10)} hisse"
        )

        # Tum basarili gun ici analizlerini Hisse Ara icin ayri kaydet.
        tum_web_dosya = os.path.join(
            os.path.dirname(__file__),
            "webapp",
            "data",
            "gun_ici_tum.json"
        )

        tum_web_veri = {
            "guncelleme": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "toplam_bist": toplam,
            "analizli": len(sonuclar),
            "hisseler": sonuclar
        }

        with open(tum_web_dosya, "w", encoding="utf-8") as f:
            json.dump(
                tum_web_veri,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )

        print(
            f"GUN ICI TUM WEB VERISI KAYDEDILDI: {len(sonuclar)} hisse"
        )

    except Exception as e:
        print("GUN ICI WEB KAYIT HATASI:", e)

    # -------------------------------------------------
    # KILITLI YARIN TOP10 HACIMLI KIRILIM TAKIBI
    # -------------------------------------------------
    # Burasi sadece kilitli listedeki canli kirilim durumunu
    # ve ilk gerceklesme saatini gunceller.
    # Sira, puan ve islem seviyeleri DEGISTIRILMEZ.
    try:
        kilitli_yarin = yarin_top10_kilitli_oku()

        if kilitli_yarin and isinstance(
            kilitli_yarin.get("top10"),
            list
        ):
            degisiklik_var = False

            for hisse in kilitli_yarin["top10"]:
                sembol = hisse.get("sembol")

                if not sembol:
                    continue

                mum_verisi = veri_map.get(sembol)

                if mum_verisi is None or mum_verisi.empty:
                    continue

                kirilim_seviyesi = guvenli_float(
                    hisse.get("yarin_kirilim")
                )

                ilk_saat, yeni_durum = ilk_hacimli_kirilim_bul(
                    mum_verisi,
                    kirilim_seviyesi
                )

                eski_saat = hisse.get(
                    "ilk_hacimli_kirilim_saati"
                )

                eski_durum = hisse.get(
                    "hacimli_kirilim_durum",
                    "BEKLENIYOR"
                )

                # Ilk gerceklesme saati bir kez bulunduysa
                # daha sonraki taramalarda ASLA degistirilmez.
                if eski_saat:
                    if eski_durum != "GERCEKLESTI":
                        hisse["hacimli_kirilim_durum"] = "GERCEKLESTI"
                        degisiklik_var = True
                    continue

                if ilk_saat:
                    hisse["ilk_hacimli_kirilim_saati"] = ilk_saat
                    hisse["hacimli_kirilim_durum"] = "GERCEKLESTI"
                    degisiklik_var = True

                elif yeni_durum != eski_durum:
                    hisse["hacimli_kirilim_durum"] = yeni_durum
                    degisiklik_var = True

            if degisiklik_var:
                with open(
                    YARIN_TOP10_FILE,
                    "w",
                    encoding="utf-8"
                ) as f:
                    json.dump(
                        kilitli_yarin,
                        f,
                        ensure_ascii=False,
                        indent=2,
                        default=str
                    )

                print(
                    "YARIN TOP10 KIRILIM TAKIBI GUNCELLENDI"
                )
            else:
                print(
                    "YARIN TOP10 KIRILIM TAKIBI: "
                    "YENI DEGISIKLIK YOK"
                )

    except Exception as e:
        print(
            "YARIN TOP10 KIRILIM TAKIP HATASI:",
            e
        )

    return top10, sonuclar, toplam


def gun_ici_top10_mesaji():
    """
    Terminal / Telegram icin okunabilir Gun Ici TOP 10.
    """

    top10, sonuclar, toplam = gun_ici_top10_tara()

    if not top10:
        return (
            "⚡ GÜN İÇİ TOP 10\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🔎 Taranan hisse: {toplam}\n"
            "Uygun gün içi aday bulunamadı."
        )

    satirlar = [
        "⚡ GÜN İÇİ TOP 10",
        "━━━━━━━━━━━━━━",
        "",
        f"🔎 Taranan hisse: {toplam}",
        f"📊 Teknik aday: {len(sonuclar)}",
        ""
    ]

    for sira, a in enumerate(
        top10,
        start=1
    ):

        satirlar.extend([
            (
                f"{sira}. {a['sembol']} — "
                f"{a['gun_ici_puan']:.0f}/100"
            ),
            (
                f"   🧠 Teknik: "
                f"{a.get('teknik_gun_ici_puan', a['gun_ici_puan']):.0f}/100 | "
                f"Haber: {a.get('haber_puani', 0):+.1f}/10"
            ),
            (
                f"   🤖 Nihai AI: "
                f"{a.get('gun_ici_nihai_ai_puan', a.get('gun_ici_puan', 0)):.0f}/100 | "
                f"{a.get('haber_sinifi', 'NOTR')} | "
                f"Güven %{a.get('haber_guven', 0):.0f}"
            ),
            (
                f"   🧭 AI Kararı: "
                f"{a.get('gun_ici_haber_ai_karar', a.get('gun_ici_karar', 'IZLE'))} | "
                f"Fiyat Teyidi "
                f"{a.get('gun_ici_haber_fiyat_teyidi', 0):+.1f}"
            ),
            (
                f"   🎯 Alım Bölgesi: "
                f"{a.get('gun_ici_alim_alt', 0):.2f} - "
                f"{a.get('gun_ici_alim_ust', 0):.2f} TL"
            ),
            (
                f"   💵 Hedef: "
                f"{a.get('gun_ici_kar_al', 0):.2f} TL | "
                f"🛑 Stop: "
                f"{a.get('gun_ici_stop', 0):.2f} TL"
            ),
            (
                f"   💰 {a['fiyat']:.2f} TL | "
                f"Açılışa göre "
                f"{a['acilisa_gore_degisim']:+.2f}%"
            ),
            (
                f"   RSI(5dk) {a['rsi5']:.1f} | "
                f"Hacim %{a['hacim3_orani']:.0f}"
            ),
            (
                f"   15dk {a['momentum15']:+.2f}% | "
                f"30dk {a['momentum30']:+.2f}%"
            ),
            (
                "   🚀 Hacimli kırılım"
                if a.get("hacimli_kirilim")
                else (
                    "   🟡 Direnç kırılımı"
                    if a.get("kirilim")
                    else "   ⚪ Kırılım bekleniyor"
                )
            ),
            ""
        ])

    return "\n".join(satirlar)




# =========================================================
# YARIN POTANSİYEL HESAPLAMA
# =========================================================

def yarin_potansiyel_hesapla(a):

    if not a:
        return -999

    degisim = guvenli_float(a.get("degisim"))
    rsi = guvenli_float(a.get("rsi"))
    fiyat = guvenli_float(a.get("fiyat"))
    sma20 = guvenli_float(a.get("sma20"))
    sma50 = guvenli_float(a.get("sma50"))
    macd = guvenli_float(a.get("macd"))
    signal = guvenli_float(a.get("signal"))
    hist = guvenli_float(a.get("hist"))
    hacim = guvenli_float(a.get("hacim_orani"))
    risk_getiri = guvenli_float(a.get("risk_getiri"))
    direnc = guvenli_float(a.get("direnc"))

    # =====================================================
    # SERT ELEME FILTRELERI
    # =====================================================

    if fiyat <= 0:
        return -999

    # Sert dusus: yarin yukselis adayi olarak alma
    if degisim <= -3:
        return -999

    # Gun icinde zaten asiri kosmus hisse
    if degisim >= 7:
        return -999

    # Asiri satim ayri sinifta degerlendirilecek
    if rsi < 30:
        return -999

    # Asiri alim
    if rsi >= 70:
        return -999

    puan = 0

    # =====================================================
    # TREND - maksimum 40
    # =====================================================

    if sma20 > 0:
        if fiyat > sma20:
            puan += 18
        else:
            puan -= 8

    if sma50 > 0:
        if fiyat > sma50:
            puan += 12
        else:
            puan -= 6

        if sma20 > sma50:
            puan += 10
        elif sma20 > 0:
            puan -= 5

    # =====================================================
    # RSI - maksimum 15
    # =====================================================

    if 45 <= rsi <= 60:
        puan += 15

    elif 40 <= rsi < 45:
        puan += 10

    elif 60 < rsi <= 64:
        puan += 10

    elif 35 <= rsi < 40:
        puan += 5

    elif 64 < rsi < 68:
        puan += 4

    elif 30 <= rsi < 35:
        puan += 1

    elif 68 <= rsi < 70:
        puan -= 4

    # =====================================================
    # MACD / MOMENTUM - maksimum 28
    # =====================================================

    if macd > signal:
        puan += 12
    else:
        puan -= 6

    if hist > 0:
        puan += 8
    else:
        puan -= 4

    if a.get("yukari_kesisim"):
        puan += 8

    # =====================================================
    # HACIM - maksimum 10
    # =====================================================

    if hacim >= 150:
        puan += 10

    elif hacim >= 120:
        puan += 7

    elif hacim >= 100:
        puan += 4

    elif hacim >= 80:
        puan += 1

    elif hacim >= 70:
        puan -= 3

    elif hacim >= 60:
        puan -= 7

    elif hacim > 0:
        puan -= 12

    # =====================================================
    # GUNLUK MOMENTUM
    # =====================================================

    if 0 < degisim <= 2.5:
        puan += 8

    elif 2.5 < degisim <= 4:
        puan += 6

    elif 4 < degisim <= 5:
        puan += 3

    elif 5 < degisim <= 6:
        puan -= 8

    elif 6 < degisim < 7:
        puan -= 15

    elif -1 < degisim <= 0:
        puan += 1

    elif -2 < degisim <= -1:
        puan -= 5

    elif -3 < degisim <= -2:
        puan -= 10

    # =====================================================
    # DIRENC MESAFESI
    # =====================================================

    if direnc > fiyat:

        direnc_mesafe = (
            (direnc - fiyat)
            / fiyat
        ) * 100

        if 7 <= direnc_mesafe <= 25:
            puan += 7

        elif 5 <= direnc_mesafe < 7:
            puan += 5

        elif 3 <= direnc_mesafe < 5:
            puan += 2

        elif 0 < direnc_mesafe < 3:
            puan -= 7

        elif 25 < direnc_mesafe <= 40:
            puan += 2

    elif direnc > 0:
        # Fiyat hesaplanan direncin ustundeyse eski direnc
        # guvenilir hedef olarak kullanilmasin.
        puan -= 3

    # =====================================================
    # RISK / GETIRI
    # =====================================================

    if risk_getiri >= 3:
        puan += 7

    elif risk_getiri >= 2:
        puan += 5

    elif risk_getiri >= 1.5:
        puan += 2

    elif 0 < risk_getiri < 1:
        puan -= 6

    # =====================================================
    # UYUM BONUSLARI / CELISKI CEZALARI
    # =====================================================

    guclu_trend = (
        sma20 > 0
        and sma50 > 0
        and fiyat > sma20 > sma50
    )

    guclu_momentum = (
        macd > signal
        and hist > 0
    )

    if guclu_trend and guclu_momentum:
        puan += 6

    if (
        guclu_trend
        and 45 <= rsi <= 64
        and hacim >= 100
    ):
        puan += 4

    # Fiyat trend altinda ama MACD tek basina olumluysa
    # yaniltici sinyal riskini azalt
    if (
        sma20 > 0
        and fiyat < sma20
        and macd > signal
    ):
        puan -= 5

    # =====================================================
    # FINAL TOP10 KALITE KAPILARI
    # =====================================================

    # Dusuk hacimli hisseler ertesi gun TOP10'a girmesin
    if hacim > 0 and hacim < 70:
        return -999

    # Gun icinde fazla kosmus hisseler ertesi gun adayi olmasin
    if degisim > 6:
        return -999

    # =====================================================
    # HABER / KAP AI KATKISI
    # =====================================================

    teknik_puan = max(
        0,
        min(95, round(puan))
    )

    try:
        haber = haber_zeka.haber_puani_getir(
            a.get("sembol")
        )

        birlesik = haber_zeka.teknik_haber_birlestir(
            teknik_puan,
            haber.get("puan", 0),
            haber.get("guven", 0)
        )

        a["teknik_puan_yarin"] = teknik_puan
        a["haber_puani"] = haber.get("puan", 0)
        a["haber_guven"] = haber.get("guven", 0)
        a["haber_sinifi"] = haber.get("sinif", "NOTR")
        a["nihai_ai_puan"] = birlesik.get(
            "nihai_puan",
            teknik_puan
        )

        # =================================================
        # MADDE 44-47 - YARIN TOP10 DINAMIK HABER AI
        # =================================================
        a["yarin_haber_ai_aktif"] = False
        a["yarin_ai_karar"] = "IZLE"
        a["yarin_haber_fiyat_teyidi"] = 0.0
        a["yarin_haber_seviye_etkisi"] = 0.0

        # Varsayilan teknik seviyeler korunur.
        a["ai_yarin_alim_alt"] = guvenli_float(
            a.get("yarin_alim_alt")
        )
        a["ai_yarin_alim_ust"] = guvenli_float(
            a.get("yarin_alim_ust")
        )
        a["ai_yarin_hedef"] = guvenli_float(
            a.get("yarin_kar_al")
        )
        a["ai_yarin_stop"] = guvenli_float(
            a.get("yarin_stop")
        )

        try:
            haber_puani_ai = guvenli_float(
                a.get("haber_puani")
            )
            haber_guven_ai = guvenli_float(
                a.get("haber_guven")
            )

            makro_canli = canli_makro_puani_getir(
                a.get("sembol")
            )

            makro_ai_puani = guvenli_float(
                makro_canli.get("makro_puani")
            )

            sektor_ai_puani = guvenli_float(
                makro_canli.get("sektor_puani")
            )

            haber_ai_aktif = (
                (
                    abs(haber_puani_ai) >= 0.5
                    and haber_guven_ai >= 25
                )
                or abs(makro_ai_puani) >= 0.5
                or abs(sektor_ai_puani) >= 0.5
            )

            a["yarin_haber_ai_aktif"] = haber_ai_aktif

            if haber_ai_aktif:

                vwap_ai_ustu = None

                vwap_durum_ai = str(
                    a.get("vwap20_durum", "")
                )

                if vwap_durum_ai == "USTUNDE":
                    vwap_ai_ustu = True
                elif vwap_durum_ai == "ALTINDA":
                    vwap_ai_ustu = False

                ai_sonuc = (
                    haber_etki_motoru.hisse_haber_ai_guncelle(
                        teknik_puan=teknik_puan,
                        fiyat=fiyat,
                        atr=max(
                            guvenli_float(a.get("atr14")),
                            fiyat * 0.003
                        ),
                        destek=guvenli_float(
                            a.get("destek")
                        ),
                        direnc=guvenli_float(
                            a.get("direnc")
                        ),
                        haber_puani=haber_puani_ai,
                        haber_guven=haber_guven_ai,
                        sektor_puani=canli_makro_puani_getir(sembol).get(
                            "sektor_puani",
                            0
                        ),
                        makro_puani=canli_makro_puani_getir(sembol).get(
                            "makro_puani",
                            0
                        ),
                        fiyat_degisim_yuzde=degisim,
                        hacim_orani=hacim,
                        vwap_ustu=vwap_ai_ustu,
                        obv_pozitif=None,
                        piyasa_rejimi=0,
                        haber_dakika=0,
                        ogrenilmis_katsayi=1.0,
                    )
                )

                a["yarin_ai_karar"] = ai_sonuc.get(
                    "ai_karar",
                    "IZLE"
                )

                a["yarin_haber_fiyat_teyidi"] = (
                    guvenli_float(
                        ai_sonuc.get("fiyat_teyidi")
                    )
                )

                a["yarin_haber_seviye_etkisi"] = (
                    guvenli_float(
                        ai_sonuc.get(
                            "haber_seviye_etkisi"
                        )
                    )
                )

                a["nihai_ai_puan"] = guvenli_float(
                    ai_sonuc.get(
                        "nihai_ai_puan",
                        a["nihai_ai_puan"]
                    )
                )

                a["ai_yarin_alim_alt"] = guvenli_float(
                    ai_sonuc.get(
                        "alim_alt",
                        a["ai_yarin_alim_alt"]
                    )
                )

                a["ai_yarin_alim_ust"] = guvenli_float(
                    ai_sonuc.get(
                        "alim_ust",
                        a["ai_yarin_alim_ust"]
                    )
                )

                a["ai_yarin_hedef"] = guvenli_float(
                    ai_sonuc.get(
                        "hedef",
                        a["ai_yarin_hedef"]
                    )
                )

                a["ai_yarin_stop"] = guvenli_float(
                    ai_sonuc.get(
                        "stop",
                        a["ai_yarin_stop"]
                    )
                )

        except Exception:
            pass

        return max(
            0,
            min(
                95,
                round(a["nihai_ai_puan"])
            )
        )

    except Exception:
        a["teknik_puan_yarin"] = teknik_puan
        a["haber_puani"] = 0
        a["haber_guven"] = 0
        a["haber_sinifi"] = "NOTR"
        a["nihai_ai_puan"] = teknik_puan
        a["yarin_haber_ai_aktif"] = False
        a["yarin_ai_karar"] = "IZLE"
        a["yarin_haber_fiyat_teyidi"] = 0.0
        a["yarin_haber_seviye_etkisi"] = 0.0
        a["ai_yarin_alim_alt"] = guvenli_float(
            a.get("yarin_alim_alt")
        )
        a["ai_yarin_alim_ust"] = guvenli_float(
            a.get("yarin_alim_ust")
        )
        a["ai_yarin_hedef"] = guvenli_float(
            a.get("yarin_kar_al")
        )
        a["ai_yarin_stop"] = guvenli_float(
            a.get("yarin_stop")
        )
        return teknik_puan


# =========================================================
# YARIN TOP 10
# =========================================================

def yarin_top10_mesaji(sonuclar=None, toplam=None):

    kilitli = yarin_top10_kilitli_oku()

    if not kilitli:
        return (
            "🏆 YARIN İÇİN TOP 10\n"
            "━━━━━━━━━━━━━━\n\n"
            "❌ Kilitli Yarın TOP10 listesi henüz oluşturulmadı.\n\n"
            "📌 Liste piyasa kapanışı sonrası oluşturulup "
            "ertesi işlem seansı için sabitlenir."
        )

    top10 = kilitli.get("top10", [])
    toplam_hisse = kilitli.get("toplam_hisse", 0)
    teknik_aday = kilitli.get("teknik_aday", 0)
    olusturma = kilitli.get("olusturma_zamani", "-")

    mesaj = (
        "🏆 YARIN İÇİN TOP 10\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🔒 Kilitli liste: {olusturma}\n"
        f"🔎 Taranan hisse: {toplam_hisse}\n"
        f"📊 Teknik aday: {teknik_aday}\n\n"
    )

    if not top10:
        mesaj += "❌ Yeterli teknik aday bulunamadı."
        return mesaj

    for i, a in enumerate(top10, 1):

        skor = int(
            guvenli_float(
                a.get("yarin_top10_puani")
            )
        )

        mesaj += (
            f"🏅 {i}. {a.get('sembol', '-')} — {skor}/100\n"
            f"   🧠 Teknik: "
            f"{guvenli_float(a.get('teknik_puan_yarin', skor)):.0f}/100 | "
            f"Haber: {guvenli_float(a.get('haber_puani', 0)):+.1f}/10\n"
            f"   🤖 Nihai AI: "
            f"{guvenli_float(a.get('nihai_ai_puan', skor)):.0f}/100 | "
            f"{a.get('haber_sinifi', 'NOTR')} | "
            f"Güven %{guvenli_float(a.get('haber_guven', 0)):.0f}\n"
            f"   🧭 AI Kararı: "
            f"{a.get('yarin_ai_karar', 'IZLE')} | "
            f"Fiyat Teyidi "
            f"{guvenli_float(a.get('yarin_haber_fiyat_teyidi', 0)):+.1f}\n"
            f"   🎯 Alım Bölgesi: "
            f"{guvenli_float(a.get('ai_yarin_alim_alt', a.get('yarin_alim_alt'))):.2f} - "
            f"{guvenli_float(a.get('ai_yarin_alim_ust', a.get('yarin_alim_ust'))):.2f} TL\n"
            f"   💵 AI Hedef: "
            f"{guvenli_float(a.get('ai_yarin_hedef', a.get('yarin_kar_al'))):.2f} TL | "
            f"🛑 AI Stop: "
            f"{guvenli_float(a.get('ai_yarin_stop', a.get('yarin_stop'))):.2f} TL\n"
            f"   💰 {guvenli_float(a.get('fiyat')):.2f} TL "
            f"({guvenli_float(a.get('degisim')):+.2f}%)\n"
            f"   RSI {guvenli_float(a.get('rsi')):.1f} | "
            f"Hacim %{guvenli_float(a.get('hacim_orani')):.0f}\n"
            f"   MACD: "
            f"{'Pozitif' if guvenli_float(a.get('macd')) > guvenli_float(a.get('signal')) else 'Negatif'}\n"
            f"   Destek {guvenli_float(a.get('destek')):.2f} | "
            f"Direnç {guvenli_float(a.get('direnc')):.2f}\n"
            f"   Hedef1 {guvenli_float(a.get('hedef1')):.2f} | "
            f"Stop {guvenli_float(a.get('stop')):.2f}\n\n"
        )

    mesaj += (
        "━━━━━━━━━━━━━━\n"
        "🔒 Bu liste oluşturulduğu seans kapanışındaki "
        "verilerle sabitlenmiştir.\n\n"
        "⚠️ Algoritmik teknik potansiyeldir; "
        "yükseliş garantisi veya yatırım tavsiyesi değildir."
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

        try:

            mesaj = yarin_top10_mesaji()

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
                f"❌ TOP 10 liste hatası:\n{e}"
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
