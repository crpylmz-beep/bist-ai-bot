
from __future__ import annotations

from datetime import datetime, timezone
import math


# =========================================================
# 44 - DINAMIK HABER ETKILI AL / SAT / STOP MOTORU
# 45 - HABER ETKI SURESI / SONUMLENME
# 46 - HABER SONRASI FIYAT TEYIDI
# 47 - HISSE / SEKTOR HABER OGRENMESI
# =========================================================


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return lo


def haber_etki_sonumleme(
    etki_puani,
    dakika,
    yarilanma_dakika=180
):
    """
    Haberin etkisini zamanla azaltir.
    Ornek:
    ilk anda +8 ise, zaman gectikce agirligi azalir.
    """
    etki = float(etki_puani or 0)
    dakika = max(0, float(dakika or 0))

    if yarilanma_dakika <= 0:
        return etki

    katsayi = 0.5 ** (dakika / yarilanma_dakika)
    return round(etki * katsayi, 2)


def fiyat_teyidi_hesapla(
    haber_etki,
    fiyat_degisim_yuzde=0,
    hacim_orani=100,
    vwap_ustu=None,
    obv_pozitif=None
):
    """
    Haber pozitif ama fiyat/hacim teyit etmiyorsa
    haber etkisini dusurur.

    Haber negatif ve fiyat da negatife gidiyorsa
    negatif etkiyi guclendirir.
    """

    haber_etki = float(haber_etki or 0)
    fiyat = float(fiyat_degisim_yuzde or 0)
    hacim = float(hacim_orani or 100)

    teyit = 0.0

    if haber_etki > 0:
        if fiyat > 0:
            teyit += min(2.0, fiyat / 2)
        elif fiyat < -1:
            teyit -= min(3.0, abs(fiyat) / 1.5)

        if hacim >= 150:
            teyit += 1.5
        elif hacim < 80:
            teyit -= 0.5

        if vwap_ustu is True:
            teyit += 1.0
        elif vwap_ustu is False:
            teyit -= 1.0

        if obv_pozitif is True:
            teyit += 0.8
        elif obv_pozitif is False:
            teyit -= 0.8

    elif haber_etki < 0:
        if fiyat < 0:
            teyit -= min(2.0, abs(fiyat) / 2)
        elif fiyat > 1:
            teyit += min(2.0, fiyat / 2)

        if hacim >= 150 and fiyat < 0:
            teyit -= 1.5

        if vwap_ustu is False:
            teyit -= 1.0
        elif vwap_ustu is True:
            teyit += 1.0

        if obv_pozitif is False:
            teyit -= 0.8
        elif obv_pozitif is True:
            teyit += 0.8

    return round(_clamp(teyit, -4, 4), 2)


def sektor_etki_hesapla(
    sektor_puani=0,
    makro_puani=0,
    hisse_duyarlilik=1.0
):
    """
    Makro + sektor etkisini hisseye uyarlar.
    """
    sektor = float(sektor_puani or 0)
    makro = float(makro_puani or 0)
    duyarlilik = _clamp(hisse_duyarlilik, 0, 2)

    sonuc = ((sektor * 0.65) + (makro * 0.35)) * duyarlilik
    return round(_clamp(sonuc, -10, 10), 2)


def nihai_ai_puan_hesapla(
    teknik_puan,
    haber_puani=0,
    haber_guven=0,
    sektor_puani=0,
    makro_puani=0,
    fiyat_teyidi=0,
    piyasa_rejimi=0,
    ogrenilmis_katsayi=1.0
):
    """
    Nihai AI puani.
    Teknik ana motor olmaya devam eder.
    Haber/makro/sektor destek ve risk katmanidir.
    """

    teknik = _clamp(teknik_puan, 0, 100)
    haber = _clamp(haber_puani, -10, 10)
    guven = _clamp(haber_guven, 0, 100) / 100
    sektor = _clamp(sektor_puani, -10, 10)
    makro = _clamp(makro_puani, -10, 10)
    fiyat = _clamp(fiyat_teyidi, -4, 4)
    rejim = _clamp(piyasa_rejimi, -5, 5)
    katsayi = _clamp(ogrenilmis_katsayi, 0.5, 1.5)

    # Teknik %70 temel.
    # Haber/makro/sektor toplamda kontrollu etki.
    haber_katki = haber * guven * 1.2
    sektor_katki = sektor * 0.7
    makro_katki = makro * 0.5
    fiyat_katki = fiyat * 1.3
    rejim_katki = rejim * 0.8

    fark = (
        haber_katki
        + sektor_katki
        + makro_katki
        + fiyat_katki
        + rejim_katki
    ) * katsayi

    # Tek haber nihai skoru asiri oynatmasin.
    fark = _clamp(fark, -20, 20)

    sonuc = teknik + fark
    return round(_clamp(sonuc, 0, 95), 1)


def karar_uret(
    nihai_ai_puan,
    haber_puani=0,
    fiyat_teyidi=0
):
    puan = float(nihai_ai_puan or 0)
    haber = float(haber_puani or 0)
    teyit = float(fiyat_teyidi or 0)

    if puan >= 82 and haber >= -2 and teyit >= -1:
        return "GUCLU_AL_ADAYI"

    if puan >= 70 and haber >= -4:
        return "AL"

    if puan <= 35 or haber <= -8:
        return "SAT"

    if puan <= 50 or haber <= -5:
        return "RISKLI_IZLE"

    return "IZLE"


def dinamik_seviyeleri_guncelle(
    fiyat,
    atr,
    destek=None,
    direnc=None,
    haber_puani=0,
    haber_guven=0,
    fiyat_teyidi=0
):
    """
    Haber etkisine gore ALIM / HEDEF / STOP seviyelerini
    yeniden hesaplar.

    Haber tek basina seviyeleri sinirsiz degistiremez.
    ATR ve destek/direnc sinirlari kullanilir.
    """

    fiyat = float(fiyat or 0)
    atr = max(0.01, float(atr or 0))
    destek = float(destek or (fiyat - atr * 1.5))
    direnc = float(direnc or (fiyat + atr * 2.0))

    haber = _clamp(haber_puani, -10, 10)
    guven = _clamp(haber_guven, 0, 100) / 100
    teyit = _clamp(fiyat_teyidi, -4, 4)

    etki = ((haber * guven) + teyit) / 14.0
    etki = _clamp(etki, -0.8, 0.8)

    # ALIM BOLGESI
    alim_alt = fiyat - atr * (0.65 - max(0, etki) * 0.15)
    alim_ust = fiyat + atr * (0.20 + max(0, etki) * 0.10)

    # STOP
    stop_katsayi = 1.35
    if etki < 0:
        stop_katsayi = 1.05
    elif etki > 0.35:
        stop_katsayi = 1.55

    stop = max(
        fiyat - atr * stop_katsayi,
        destek - atr * 0.35
    )

    # HEDEF
    hedef_katsayi = 1.8 + max(0, etki) * 1.2
    if etki < 0:
        hedef_katsayi = 1.35

    hedef = fiyat + atr * hedef_katsayi

    if direnc > fiyat:
        if etki < 0.25:
            hedef = min(hedef, direnc)
        else:
            hedef = min(
                hedef,
                direnc + atr * 0.75
            )

    return {
        "alim_alt": round(alim_alt, 2),
        "alim_ust": round(alim_ust, 2),
        "hedef": round(hedef, 2),
        "stop": round(stop, 2),
        "haber_seviye_etkisi": round(etki, 3),
    }


def hisse_haber_ai_guncelle(
    teknik_puan,
    fiyat,
    atr,
    destek=None,
    direnc=None,
    haber_puani=0,
    haber_guven=0,
    sektor_puani=0,
    makro_puani=0,
    fiyat_degisim_yuzde=0,
    hacim_orani=100,
    vwap_ustu=None,
    obv_pozitif=None,
    piyasa_rejimi=0,
    haber_dakika=0,
    ogrenilmis_katsayi=1.0
):
    """
    Tek cagri ile:
    - haber sonumleme
    - fiyat teyidi
    - nihai AI skoru
    - AL/SAT/IZLE
    - dinamik hedef / stop / alim bolgesi
    """

    sonumlu_haber = haber_etki_sonumleme(
        haber_puani,
        haber_dakika
    )

    teyit = fiyat_teyidi_hesapla(
        sonumlu_haber,
        fiyat_degisim_yuzde,
        hacim_orani,
        vwap_ustu,
        obv_pozitif
    )

    nihai = nihai_ai_puan_hesapla(
        teknik_puan=teknik_puan,
        haber_puani=sonumlu_haber,
        haber_guven=haber_guven,
        sektor_puani=sektor_puani,
        makro_puani=makro_puani,
        fiyat_teyidi=teyit,
        piyasa_rejimi=piyasa_rejimi,
        ogrenilmis_katsayi=ogrenilmis_katsayi
    )

    karar = karar_uret(
        nihai,
        sonumlu_haber,
        teyit
    )

    seviyeler = dinamik_seviyeleri_guncelle(
        fiyat=fiyat,
        atr=atr,
        destek=destek,
        direnc=direnc,
        haber_puani=sonumlu_haber,
        haber_guven=haber_guven,
        fiyat_teyidi=teyit
    )

    return {
        "teknik_puan": round(float(teknik_puan or 0), 1),
        "haber_puani": round(float(sonumlu_haber), 2),
        "haber_guven": round(float(haber_guven or 0), 1),
        "sektor_puani": round(float(sektor_puani or 0), 2),
        "makro_puani": round(float(makro_puani or 0), 2),
        "fiyat_teyidi": round(float(teyit), 2),
        "nihai_ai_puan": nihai,
        "ai_karar": karar,
        **seviyeler
    }
