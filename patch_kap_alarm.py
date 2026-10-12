from pathlib import Path

p = Path("haber_zeka.py")
s = p.read_text(encoding="utf-8")

if "def kap_alarm_uret(" in s:
    print("KAP ALARM MOTORU ZATEN VAR")
    raise SystemExit

ek = r'''

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
'''

s += ek

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP AI ALARM MOTORU EKLENDI")
