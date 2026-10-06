
from __future__ import annotations
from veri_yollari import public_file, runtime_file


import json
import hashlib
from kullanici_kayitlari import atomic_json, now
from pathlib import Path

import sektor_haritasi
import canli_motor


# =========================================================
# BIST ASISTANI - MAKRO / EKONOMI AI MOTORU
# =========================================================

MAKRO_GECMIS = runtime_file('makro_ai_gecmisi.json')

CANLI_MAKRO_DOSYA = public_file('makro_canli_etki.json')


# Gercek borsapy sektor adlarimiz.
SEKTORLER = {
    "BILGI": "BİLGİ VE İLETİŞİM",
    "ENERJI": "ELEKTRİK GAZ VE SU",
    "SAGLIK": "EĞİTİM SAĞLIK SPOR VE EĞLENCE HİZMETLERİ",
    "GYO": "GAYRİMENKUL FAALİYETLERİ",
    "MADEN": "MADENCİLİK VE TAŞ OCAKÇILIĞI",
    "MALI": "MALİ KURULUŞLAR",
    "PROFESYONEL": "MESLEKİ, BİLİMSEL VE TEKNİK FAALİYETLER",
    "TURIZM": "OTELLER VE LOKANTALAR",
    "TARIM": "TARIM, ORMANCILIK VE BALIKÇILIK",
    "TEKNOLOJI": "TEKNOLOJİ",
    "TICARET": "TOPTAN VE PERAKENDE TİCARET",
    "ULASTIRMA": "ULAŞTIRMA VE DEPOLAMA",
    "IMALAT": "İMALAT",
    "INSAAT": "İNŞAAT VE BAYINDIRLIK",
}


def _clamp(v, lo, hi):
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return lo


def makro_etki_analiz_et(
    baslik,
    metin="",
    kaynak="EKONOMI"
):
    """
    Ilk surum kural tabanli makro yorumlayici.

    Sonraki adimda bunu haber kaynagi + LLM / AI yorumuna
    baglayacagiz.
    """

    yazi = (
        str(baslik or "")
        + " "
        + str(metin or "")
    ).lower()

    sektor_etkileri = {}
    genel_puan = 0.0
    kategori = "GENEL"

    # -----------------------------------------------------
    # TCMB / FAIZ
    # -----------------------------------------------------
    if any(
        x in yazi
        for x in [
            "tcmb",
            "politika faizi",
            "faiz kararı",
            "faiz indir",
            "faiz artır",
            "faiz artir",
        ]
    ):
        kategori = "FAIZ"

        if any(
            x in yazi
            for x in [
                "faiz indir",
                "indirim",
                "beklentinin altında faiz",
            ]
        ):
            genel_puan += 2.0

            sektor_etkileri.update({
                SEKTORLER["GYO"]: 5.0,
                SEKTORLER["INSAAT"]: 4.0,
                SEKTORLER["MALI"]: 3.0,
                SEKTORLER["TICARET"]: 2.0,
            })

        if any(
            x in yazi
            for x in [
                "faiz artır",
                "faiz artir",
                "faiz artışı",
                "faiz artisi",
            ]
        ):
            genel_puan -= 2.0

            sektor_etkileri.update({
                SEKTORLER["GYO"]: -5.0,
                SEKTORLER["INSAAT"]: -4.0,
                SEKTORLER["TICARET"]: -2.0,
            })

    # -----------------------------------------------------
    # ENFLASYON
    # -----------------------------------------------------
    if any(
        x in yazi
        for x in [
            "enflasyon",
            "tüfe",
            "tuik",
            "tüik",
        ]
    ):
        kategori = "ENFLASYON"

        if any(
            x in yazi
            for x in [
                "beklentinin üzerinde",
                "beklentiden yüksek",
                "yükseldi",
                "arttı",
            ]
        ):
            genel_puan -= 2.0

            sektor_etkileri.update({
                SEKTORLER["GYO"]: -2.5,
                SEKTORLER["INSAAT"]: -2.0,
                SEKTORLER["TICARET"]: -1.5,
            })

        elif any(
            x in yazi
            for x in [
                "beklentinin altında",
                "beklentiden düşük",
                "geriledi",
                "düştü",
            ]
        ):
            genel_puan += 2.0

            sektor_etkileri.update({
                SEKTORLER["GYO"]: 2.5,
                SEKTORLER["INSAAT"]: 2.0,
                SEKTORLER["MALI"]: 1.5,
            })

    # -----------------------------------------------------
    # PETROL
    # -----------------------------------------------------
    if any(
        x in yazi
        for x in [
            "brent",
            "ham petrol",
            "petrol fiyat",
            "petrol yükseldi",
            "petrol düştü",
        ]
    ):
        kategori = "PETROL"

        if any(
            x in yazi
            for x in [
                "yükseldi",
                "arttı",
                "artış",
                "sıçradı",
            ]
        ):
            sektor_etkileri.update({
                SEKTORLER["ULASTIRMA"]: -5.0,
                SEKTORLER["IMALAT"]: -1.0,
            })

        elif any(
            x in yazi
            for x in [
                "düştü",
                "geriledi",
                "düşüş",
            ]
        ):
            sektor_etkileri.update({
                SEKTORLER["ULASTIRMA"]: 5.0,
                SEKTORLER["IMALAT"]: 1.0,
            })

    # -----------------------------------------------------
    # DOVIZ / TL
    # -----------------------------------------------------
    if any(
        x in yazi
        for x in [
            "dolar/tl",
            "usdtry",
            "döviz",
            "kur yükseldi",
            "tl değer kaybetti",
            "tl deger kaybetti",
        ]
    ):
        kategori = "DOVIZ"

        if any(
            x in yazi
            for x in [
                "yükseldi",
                "değer kaybetti",
                "deger kaybetti",
            ]
        ):
            genel_puan -= 1.0

            sektor_etkileri.update({
                SEKTORLER["ULASTIRMA"]: -2.0,
                SEKTORLER["TICARET"]: -1.0,
            })

    # -----------------------------------------------------
    # ALTIN / MADEN
    # -----------------------------------------------------
    if any(
        x in yazi
        for x in [
            "altın",
            "altin",
            "ons altın",
            "ons altin",
        ]
    ):
        kategori = "ALTIN"

        if any(
            x in yazi
            for x in [
                "yükseldi",
                "arttı",
                "rekor",
            ]
        ):
            sektor_etkileri[
                SEKTORLER["MADEN"]
            ] = 3.0

    # -----------------------------------------------------
    # FED / ABD FAIZI
    # -----------------------------------------------------
    if any(
        x in yazi
        for x in [
            "fed",
            "fomc",
            "powell",
            "abd faiz",
        ]
    ):
        kategori = "FED"

        if any(
            x in yazi
            for x in [
                "faiz indir",
                "güvercin",
                "guvercin",
            ]
        ):
            genel_puan += 2.0

        if any(
            x in yazi
            for x in [
                "faiz artır",
                "faiz artir",
                "şahin",
                "sahin",
            ]
        ):
            genel_puan -= 2.0

    genel_puan = round(
        _clamp(genel_puan, -10, 10),
        2
    )

    sektor_etkileri = {
        k: round(
            _clamp(v, -10, 10),
            2
        )
        for k, v in sektor_etkileri.items()
    }

    return {
        "kaynak": kaynak,
        "kategori": kategori,
        "baslik": baslik,
        "genel_puan": genel_puan,
        "sektor_etkileri": sektor_etkileri,
    }


def etkilenen_hisseleri_bul(analiz):
    """
    Sektor etkilerini 805 hisselik sektor haritamizla
    eslestirir.
    """

    sonuc = {}

    for sektor, puan in analiz.get(
        "sektor_etkileri",
        {}
    ).items():

        hisseler = (
            sektor_haritasi.sektor_hisseleri(
                sektor
            )
        )

        for sembol in hisseler:
            sonuc[sembol] = {
                "sektor": sektor,
                "makro_puani": puan
            }

    return sonuc




def canli_makro_etki_yaz(analiz, hisseler):
    """
    Son makro olayinin hisse bazli etkisini kalici JSON'a yazar.
    Bist karar motorlari bu dosyayi anlik okur.
    """
    import time

    veri = {
        "guncelleme": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "kategori": analiz.get(
            "kategori",
            "GENEL"
        ),
        "baslik": analiz.get(
            "baslik",
            ""
        ),
        "genel_puan": analiz.get(
            "genel_puan",
            0
        ),
        "hisseler": {}
    }
    veri['updated_at'] = now()
    veri['event_id'] = analiz.get('canonical_id') or hashlib.sha256(
        json.dumps([analiz.get('kaynak'),analiz.get('baslik'),analiz.get('kategori'),
                    veri['updated_at'][:10]],ensure_ascii=False).encode()).hexdigest()

    for sembol, bilgi in hisseler.items():
        veri["hisseler"][sembol] = {
            "event_id": veri['event_id'],
            "sektor_event_id": veri['event_id'],
            "makro_puani": float(
                bilgi.get(
                    "makro_puani",
                    0
                ) or 0
            ),
            "sektor": bilgi.get(
                "sektor",
                ""
            ),
            "sektor_puani": float(
                bilgi.get(
                    "makro_puani",
                    0
                ) or 0
            )
        }

    CANLI_MAKRO_DOSYA.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    atomic_json(CANLI_MAKRO_DOSYA, veri)

    # Keep observation metadata for 1/3/5-session outcome tracking, not new scores.
    from ai_karar_motoru import locked, load, stamp, number, ISTANBUL
    from datetime import datetime
    from veri_yollari import public_file
    current=datetime.now(ISTANBUL)
    live=load(public_file('bist_data.json'),{'hisseler':[]})
    quotes={r.get('sembol'):r for r in live.get('hisseler',[]) if isinstance(r,dict)}
    observed=json.loads(json.dumps(veri))
    for stock,row in observed['hisseler'].items():
        quote=quotes.get(stock,{})
        at=stamp(quote.get('canli_guncelleme') or quote.get('updated_at'))
        row['referans_fiyat']=number(quote.get('fiyat')) if at and 0<=(current-at).total_seconds()<=1200 else None
        row['referans_fiyat_zamani']=at.isoformat() if row['referans_fiyat'] else None
    with locked(MAKRO_GECMIS):
        history=load(MAKRO_GECMIS,{'olaylar':[]})
        if not isinstance(history,dict):history={'legacy':history,'olaylar':[]}
        events=history.setdefault('olaylar',[])
        if not any(e.get('event_id')==veri['event_id'] for e in events):
            events.append(observed)
            atomic_json(MAKRO_GECMIS,history)

    return veri


def makro_haber_isle(
    baslik,
    metin="",
    kaynak="EKONOMI",
    max_canli_hisse=40
):
    """
    Makro haber:
    analiz -> sektor -> ilgili hisseler ->
    canli yeniden analiz.
    """

    analiz = makro_etki_analiz_et(
        baslik,
        metin,
        kaynak
    )

    hisseler = etkilenen_hisseleri_bul(
        analiz
    )

    # Hisse bazli makro/sektor etkisini karar motorlarina aktar.
    canli_makro_etki_yaz(
        analiz,
        hisseler
    )

    print(
        "MAKRO AI | "
        f"{analiz['kategori']} | "
        f"Genel {analiz['genel_puan']:+.1f} | "
        f"Etkilenen hisse: {len(hisseler)}"
    )

    # Ilk surumde veri kaynagini ezmemek icin
    # tek haberde maksimum 40 hisse aninda yenilenir.
    # Digerleri genel canli turda zaten guncellenir.
    adet = 0

    for sembol, bilgi in hisseler.items():

        if adet >= max_canli_hisse:
            break

        try:
            canli_motor.oncelikli_hisse_guncelle(
                sembol,
                gun_ici_yenile=False
            )

            adet += 1

        except Exception:
            raise

    # Bir kez Gun Ici TOP10 yenile.
    if adet > 0:
        try:
            canli_motor.gun_ici_top10_guncelle()
        except Exception:
            pass

    return {
        "analiz": analiz,
        "etkilenen_hisseler": hisseler,
        "aninda_guncellenen": adet,
    }
