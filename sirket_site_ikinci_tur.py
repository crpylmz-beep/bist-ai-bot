from veri_yollari import public_file, runtime_file
from pathlib import Path
import json
import time
import borsapy as bp

DOSYA = public_file('sirket_site_haritasi.json')

veri = json.loads(
    DOSYA.read_text(encoding="utf-8")
)

hisseler = veri.get("hisseler", {})

eksikler = [
    s
    for s, v in hisseler.items()
    if not v.get("siteler")
]

print(
    f"IKINCI SITE TARAMASI | "
    f"Eksik: {len(eksikler)}"
)

bulunan = 0
hata = 0


def url_ayir(metin):
    import re

    bulunan_url = re.findall(
        r'(?:(?:https?://)?(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)',
        str(metin or "")
    )

    sonuc = []

    for url in bulunan_url:
        url = url.strip(" ,;()[]")

        if not url:
            continue

        if not url.startswith(
            ("http://", "https://")
        ):
            url = "https://" + url

        if url not in sonuc:
            sonuc.append(url)

    return sonuc


for no, sembol in enumerate(eksikler, 1):

    website = ""
    son_hata = ""

    for deneme in range(3):

        try:
            info = bp.Ticker(
                sembol
            ).info or {}

            website = str(
                info.get("website") or ""
            ).strip()

            if website:
                break

        except Exception as e:
            son_hata = str(e)

        time.sleep(
            1.0 + deneme
        )

    siteler = url_ayir(
        website
    )

    if siteler:
        hisseler[sembol]["website_ham"] = website
        hisseler[sembol]["siteler"] = siteler
        hisseler[sembol]["site_adedi"] = len(siteler)
        hisseler[sembol]["site_durumu"] = "BULUNDU_2_TUR"
        bulunan += 1

    else:
        hisseler[sembol]["site_durumu"] = "IKINCI_KAYNAK_GEREKLI"
        hisseler[sembol]["son_hata"] = son_hata[:200]
        hata += 1

    if no % 25 == 0 or no == len(eksikler):
        print(
            f"IKINCI TUR: {no}/{len(eksikler)} | "
            f"Yeni bulunan: {bulunan} | "
            f"Ikinci kaynak: {hata}"
        )

        veri["hisseler"] = hisseler
        veri["site_bulunan_hisse"] = sum(
            1
            for x in hisseler.values()
            if x.get("siteler")
        )

        DOSYA.write_text(
            json.dumps(
                veri,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

print(
    "IKINCI SITE TARAMASI TAMAM | "
    f"Yeni bulunan: {bulunan} | "
    f"Toplam site: {veri['site_bulunan_hisse']}"
)
