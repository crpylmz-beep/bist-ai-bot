
from __future__ import annotations
from veri_yollari import public_file, runtime_file


import json
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import borsapy as bp


DOSYA = public_file('sirket_site_haritasi.json')

MAX_WORKERS = 6


def url_ayir(metin):
    metin = str(metin or "").strip()

    if not metin:
        return []

    bulunan = re.findall(
        r'(?:(?:https?://)?(?:www\.)?[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)',
        metin
    )

    sonuc = []

    for url in bulunan:
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


def tek_hisse_site(sembol):
    try:
        info = bp.Ticker(
            sembol
        ).info or {}

        ham = info.get(
            "website",
            ""
        )

        siteler = url_ayir(
            ham
        )

        return {
            "sembol": sembol,
            "website_ham": str(ham or ""),
            "siteler": siteler,
            "site_adedi": len(siteler)
        }

    except Exception:
        return {
            "sembol": sembol,
            "website_ham": "",
            "siteler": [],
            "site_adedi": 0
        }


def harita_olustur():

    df = bp.companies()

    semboller = [
        str(x).strip().upper()
        for x in df["ticker"].tolist()
        if str(x).strip()
    ]

    toplam = len(semboller)

    print(
        f"SIRKET SITE HARITASI BASLADI | "
        f"{toplam} hisse"
    )

    hisseler = {}
    tamam = 0
    site_bulunan = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as ex:

        gorevler = {
            ex.submit(
                tek_hisse_site,
                sembol
            ): sembol
            for sembol in semboller
        }

        for future in as_completed(
            gorevler
        ):

            sembol = gorevler[
                future
            ]

            try:
                veri = future.result()
            except Exception:
                veri = {
                    "sembol": sembol,
                    "website_ham": "",
                    "siteler": [],
                    "site_adedi": 0
                }

            hisseler[
                sembol
            ] = veri

            tamam += 1

            if veri.get(
                "site_adedi",
                0
            ) > 0:
                site_bulunan += 1

            if (
                tamam % 50 == 0
                or tamam == toplam
            ):
                print(
                    f"SITE: {tamam}/{toplam} | "
                    f"Site bulunan: {site_bulunan}"
                )

    veri = {
        "guncelleme": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "toplam_hisse": toplam,
        "site_bulunan_hisse": site_bulunan,
        "hisseler": hisseler
    }

    DOSYA.parent.mkdir(
        parents=True,
        exist_ok=True
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
        f"SIRKET SITE HARITASI TAMAM | "
        f"{site_bulunan}/{toplam}"
    )

    return veri


if __name__ == "__main__":
    harita_olustur()
