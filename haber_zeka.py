from veri_yollari import data_file
import os
import fcntl
from functools import wraps
import json
from pathlib import Path
from kullanici_kayitlari import atomic_json
import re
import hashlib
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HABER_FILE = str(data_file("haber_zeka_gecmisi.json"))
DATA_DIR = str(Path(HABER_FILE).parent)

POZITIF_KELIMELER = {
    "sozlesme": 2.5,
    "ihale": 1.5,
    "siparis": 2.0,
    "yatirim": 1.2,
    "tesvik": 1.8,
    "onay": 1.2,
    "ruhsat": 1.2,
    "temettu": 1.4,
    "kar payi": 1.4,
    "geri alim": 1.8,
    "bedelsiz": 1.0,
    "ihracat": 1.5,
    "yeni pazar": 1.5,
    "kapasite artisi": 1.6,
    "uretim artisi": 1.4,
    "borc odeme": 1.2,
    "kredi notu artisi": 2.0,
    "kar artisi": 2.2,
    "net kar": 1.0,
}

NEGATIF_KELIMELER = {
    "zarar": -2.0,
    "dava": -1.5,
    "ceza": -2.0,
    "sorusturma": -1.8,
    "faaliyet durdurma": -3.0,
    "uretim durdu": -3.0,
    "uretime ara": -2.5,
    "iflas": -5.0,
    "konkordato": -5.0,
    "temerrut": -4.0,
    "borc yapilandirma": -2.0,
    "kredi notu dususu": -2.2,
    "sermaye kaybi": -3.0,
    "bedelli": -0.8,
    "pay satisi": -1.0,
    "ortak satisi": -1.3,
    "kar dususu": -2.0,
}

RUTIN_KELIMELER = {
    "genel kurul", "yonetim kurulu", "komite", "bagimsiz denetim",
    "faaliyet raporu", "surdurulebilirlik", "esas sozlesme"
}

YUKSEK_ONEM = {
    "sozlesme", "ihale", "siparis", "iflas", "konkordato", "temerrut",
    "faaliyet durdurma", "uretim durdu", "ceza", "sorusturma",
    "birlesme", "devralma", "satinalma", "temettu", "geri alim"
}


def _normalize(text):
    text = (text or "").lower()
    ceviri = str.maketrans("çğıöşü", "cgiosu")
    text = text.translate(ceviri)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load():
    try:
        if not os.path.exists(HABER_FILE):
            return {"surum": 1, "haberler": []}

        with open(HABER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        data.setdefault("surum", 1)
        data.setdefault("haberler", [])
        return data

    except Exception:
        return {"surum": 1, "haberler": []}


def _save(data):
    os.makedirs(DATA_DIR, exist_ok=True)

    atomic_json(Path(HABER_FILE), data)


def _haber_id(sembol, baslik, metin, tarih):
    raw = f"{sembol}|{baslik}|{metin}|{tarih}".encode(
        "utf-8",
        errors="ignore"
    )
    return hashlib.sha1(raw).hexdigest()[:16]


def etki_sinifi(puan):
    if puan >= 6:
        return "GUCLU_POZITIF"

    if puan >= 2:
        return "POZITIF"

    if puan <= -6:
        return "GUCLU_NEGATIF"

    if puan <= -2:
        return "NEGATIF"

    return "NOTR"


def kap_haber_analiz_et(
    sembol,
    baslik,
    metin,
    kaynak="KAP",
    fiyat_verisi=None
):
    sembol = (sembol or "").upper().strip()
    tam = _normalize(
        f"{baslik or ''} {metin or ''}"
    )

    puan = 0.0
    bulunan = []

    for kelime, agirlik in POZITIF_KELIMELER.items():
        if _normalize(kelime) in tam:
            puan += agirlik
            bulunan.append(
                f"+ {kelime}"
            )

    for kelime, agirlik in NEGATIF_KELIMELER.items():
        if _normalize(kelime) in tam:
            puan += agirlik
            bulunan.append(
                f"- {kelime}"
            )

    rutin = any(
        _normalize(k) in tam
        for k in RUTIN_KELIMELER
    )

    yuksek_onem = any(
        _normalize(k) in tam
        for k in YUKSEK_ONEM
    )

    if rutin and not yuksek_onem:
        puan *= 0.45

    puan = max(
        -10.0,
        min(10.0, puan)
    )

    onem = 80 if yuksek_onem else 55

    if rutin and not yuksek_onem:
        onem = 30

    guven = 45 + min(
        40,
        len(bulunan) * 8
    )

    if kaynak.upper() == "KAP":
        guven += 10

    guven = max(
        0,
        min(95, guven)
    )

    fiyatlandi_riski = "BILINMIYOR"

    if isinstance(fiyat_verisi, dict):
        gunluk = float(
            fiyat_verisi.get("degisim", 0) or 0
        )

        hacim = float(
            fiyat_verisi.get(
                "hacim_orani",
                100
            ) or 100
        )

        if puan > 0 and gunluk >= 6:
            fiyatlandi_riski = "YUKSEK"

        elif puan > 0 and gunluk >= 3:
            fiyatlandi_riski = "ORTA"

        elif puan < 0 and gunluk <= -6:
            fiyatlandi_riski = "YUKSEK"

        elif abs(gunluk) < 2 and hacim < 130:
            fiyatlandi_riski = "DUSUK"

        else:
            fiyatlandi_riski = "ORTA"

    return {
        "sembol": sembol,
        "kaynak": kaynak,
        "baslik": baslik or "",
        "metin": metin or "",
        "etki_puani": round(
            puan,
            2
        ),
        "etki_sinifi": etki_sinifi(
            puan
        ),
        "guven": int(guven),
        "onem": int(onem),
        "fiyatlandi_riski": fiyatlandi_riski,
        "nedenler": bulunan[:10],
    }


def _haber_kayit_kilidi(function):
    @wraps(function)
    def locked(*args, **kwargs):
        # KAP and company collectors share this history: serialize read/modify/write.
        target = Path(kwargs.get("store_path") or HABER_FILE)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(str(target) + ".lock", "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return function(*args, **kwargs)
    return locked


@_haber_kayit_kilidi
def haber_kaydet(
    analiz,
    tarih=None,
    fiyat=None,
    store_path=None
):
    tarih = (
        tarih
        or datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    target = Path(store_path) if store_path is not None else Path(HABER_FILE)
    data = json.loads(target.read_text()) if store_path is not None and target.exists() else (_load() if store_path is None else {"surum":1,"haberler":[]})

    hid = analiz.get("canonical_id") or _haber_id(
        analiz.get("sembol"),
        analiz.get("baslik"),
        analiz.get("metin"),
        tarih
    )

    if any(
        x.get("id") == hid
        for x in data["haberler"]
    ):
        return False

    kayit = dict(analiz)

    kayit.update({
        "id": hid,
        "tarih": tarih,
        "ilk_fiyat": fiyat,
        "sonuc_5dk": None,
        "sonuc_15dk": None,
        "sonuc_30dk": None,
        "sonuc_60dk": None,
        "sonuc_1g": None,
        "sonuc_3g": None,
        "sonuc_5g": None,
        "degerlendirme": None,
    })

    data["haberler"].append(
        kayit
    )

    atomic_json(target, data) if store_path is not None else _save(data)

    return True


def haber_puani_getir(
    sembol,
    max_adet=5
):
    sembol = (
        sembol
        or ""
    ).upper().strip()

    data = _load()

    adaylar = [
        x
        for x in data["haberler"]
        if x.get("sembol") == sembol
    ]

    adaylar = adaylar[
        -max_adet:
    ]

    if not adaylar:
        return {
            "puan": 0.0,
            "guven": 0,
            "adet": 0,
            "sinif": "NOTR"
        }

    agirlikli = 0.0
    agirlik = 0.0

    for i, h in enumerate(
        reversed(adaylar),
        start=1
    ):
        w = 1.0 / i

        agirlikli += (
            float(
                h.get(
                    "etki_puani",
                    0
                ) or 0
            )
            * w
        )

        agirlik += w

    puan = (
        agirlikli / agirlik
        if agirlik
        else 0.0
    )

    guven = max(
        int(
            h.get(
                "guven",
                0
            ) or 0
        )
        for h in adaylar
    )

    return {
        "puan": round(
            max(
                -10,
                min(10, puan)
            ),
            2
        ),
        "guven": guven,
        "adet": len(adaylar),
        "sinif": etki_sinifi(
            puan
        ),
    }


def haber_yasi_getir(sembol, current=None):
    """Use actual stored news time; undated news is never treated as fresh."""
    from ai_karar_motoru import ISTANBUL, minutes
    current = current or datetime.now(ISTANBUL)
    rows = [r for r in _load().get('haberler',[]) if r.get('sembol') == sembol]
    ages = [minutes(r.get('published_at') or r.get('tarih'),current) for r in rows[-5:]]
    ages = [a for a in ages if a is not None]
    return min(ages) if ages else 1440


def teknik_haber_birlestir(
    teknik_puan,
    haber_puani,
    haber_guven=0
):
    teknik = float(
        teknik_puan or 0
    )

    hp = float(
        haber_puani or 0
    )

    guven = max(
        0.0,
        min(
            100.0,
            float(
                haber_guven or 0
            )
        )
    ) / 100.0

    katkı = hp * guven

    katkı = max(
        -10.0,
        min(10.0, katkı)
    )

    nihai = max(
        0.0,
        min(
            100.0,
            teknik + katkı
        )
    )

    return {
        "teknik_puan": round(
            teknik,
            2
        ),
        "haber_katkisi": round(
            katkı,
            2
        ),
        "nihai_puan": round(
            nihai,
            2
        ),
    }


def bildirim_metni(analiz):
    sinif = analiz.get(
        "etki_sinifi",
        "NOTR"
    )

    ikon = {
        "GUCLU_POZITIF": "🚨🟢",
        "POZITIF": "🟢",
        "NOTR": "⚪",
        "NEGATIF": "🔴",
        "GUCLU_NEGATIF": "🚨🔴",
    }.get(
        sinif,
        "⚪"
    )

    return (
        f"{ikon} "
        f"{analiz.get('sembol','')} — "
        f"{sinif.replace('_',' ')}\n"
        f"AI Haber Etkisi: "
        f"{analiz.get('etki_puani',0):+.1f}/10\n"
        f"Güven: "
        f"%{analiz.get('guven',0)} | "
        f"Önem: %{analiz.get('onem',0)}\n"
        f"Fiyatlanma riski: "
        f"{analiz.get('fiyatlandi_riski','BILINMIYOR')}\n"
        f"{analiz.get('baslik','')[:180]}"
    )

def kap_alarm_uret(analiz):
    """
    KAP/haber analizinden alarm karari üretir.
    Yalnizca anlamli ve guvenilir haberlerde alarm verir.
    """

    if not isinstance(analiz, dict):
        return {
            "alarm": False,
            "seviye": "YOK",
            "mesaj": ""
        }

    puan = float(
        analiz.get("etki_puani", 0) or 0
    )

    guven = float(
        analiz.get("guven", 0) or 0
    )

    onem = float(
        analiz.get("onem", 0) or 0
    )

    sinif = analiz.get(
        "etki_sinifi",
        "NOTR"
    )

    fiyatlandi = analiz.get(
        "fiyatlandi_riski",
        "BILINMIYOR"
    )

    alarm = False
    seviye = "YOK"

    if (
        sinif == "GUCLU_POZITIF"
        and guven >= 70
        and onem >= 70
    ):
        alarm = True
        seviye = "GUCLU_POZITIF"

    elif (
        sinif == "POZITIF"
        and puan >= 3
        and guven >= 75
        and onem >= 60
    ):
        alarm = True
        seviye = "POZITIF"

    elif (
        sinif == "GUCLU_NEGATIF"
        and guven >= 70
        and onem >= 70
    ):
        alarm = True
        seviye = "GUCLU_NEGATIF"

    elif (
        sinif == "NEGATIF"
        and puan <= -3
        and guven >= 75
        and onem >= 60
    ):
        alarm = True
        seviye = "NEGATIF"

    if not alarm:
        return {
            "alarm": False,
            "seviye": "YOK",
            "mesaj": ""
        }

    sembol = analiz.get(
        "sembol",
        "-"
    )

    baslik = analiz.get(
        "baslik",
        ""
    )

    if seviye in (
        "GUCLU_POZITIF",
        "POZITIF"
    ):
        ikon = "🚨🟢"
        yon = "YUKARI YONLU ETKI IHTIMALI ARTTI"
    else:
        ikon = "🚨🔴"
        yon = "ASAGI YONLU BASKI RISKI ARTTI"

    mesaj = (
        f"{ikon} KAP AI ALARMI\n"
        f"{sembol}\n\n"
        f"{baslik[:180]}\n\n"
        f"AI Etki: {puan:+.1f}/10\n"
        f"Guven: %{guven:.0f}\n"
        f"Onem: %{onem:.0f}\n"
        f"Sinif: {sinif}\n"
        f"Fiyatlanma riski: {fiyatlandi}\n\n"
        f"{yon}"
    )

    return {
        "alarm": True,
        "seviye": seviye,
        "mesaj": mesaj
    }


def kap_haber_isle(
    sembol,
    baslik,
    metin,
    kaynak="KAP",
    fiyat_verisi=None
):
    """
    Tek adimda:
    analiz et -> kaydet -> alarm üret
    """

    analiz = kap_haber_analiz_et(
        sembol=sembol,
        baslik=baslik,
        metin=metin,
        kaynak=kaynak,
        fiyat_verisi=fiyat_verisi
    )

    fiyat = None

    if isinstance(
        fiyat_verisi,
        dict
    ):
        fiyat = fiyat_verisi.get(
            "fiyat"
        )

    haber_kaydet(
        analiz,
        fiyat=fiyat
    )

    alarm = kap_alarm_uret(
        analiz
    )

    return {
        "analiz": analiz,
        "alarm": alarm
    }
