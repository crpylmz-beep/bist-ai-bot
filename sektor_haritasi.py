
from __future__ import annotations

import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import borsapy as bp


DOSYA = Path("webapp/data/sektor_haritasi.json")
MAX_WORKERS = 6


def _norm(v):
    return str(v or "").strip()


def sektor_bilgisi_al(sembol):
    try:
        info = bp.Ticker(sembol).info or {}

        return {
            "sembol": sembol,
            "sektor": _norm(info.get("sector")) or "BILINMIYOR",
            "alt_sektor": _norm(info.get("industry")) or "BILINMIYOR",
        }

    except Exception:
        return {
            "sembol": sembol,
            "sektor": "BILINMIYOR",
            "alt_sektor": "BILINMIYOR",
        }


def sektor_haritasi_olustur():
    df = bp.companies()

    semboller = [
        str(x).strip().upper()
        for x in df["ticker"].tolist()
        if str(x).strip()
    ]

    toplam = len(semboller)

    print(
        f"SEKTOR HARITASI BASLADI | {toplam} hisse"
    )

    sonuclar = {}
    tamam = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as ex:

        gorevler = {
            ex.submit(
                sektor_bilgisi_al,
                s
            ): s
            for s in semboller
        }

        for future in as_completed(gorevler):

            s = gorevler[future]

            try:
                veri = future.result()
            except Exception:
                veri = {
                    "sembol": s,
                    "sektor": "BILINMIYOR",
                    "alt_sektor": "BILINMIYOR",
                }

            sonuclar[s] = veri
            tamam += 1

            if tamam % 50 == 0 or tamam == toplam:
                print(
                    f"SEKTOR: {tamam}/{toplam}"
                )

    veri = {
        "guncelleme": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "toplam": toplam,
        "hisseler": sonuclar
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
        f"SEKTOR HARITASI TAMAM | {len(sonuclar)} hisse"
    )

    return veri


def sektor_haritasi_oku():
    if not DOSYA.exists():
        return sektor_haritasi_olustur()

    try:
        return json.loads(
            DOSYA.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return sektor_haritasi_olustur()


def sektor_hisseleri(sektor_adi):
    veri = sektor_haritasi_oku()
    hedef = str(sektor_adi or "").strip().upper()

    sonuc = []

    for sembol, bilgi in veri.get(
        "hisseler",
        {}
    ).items():

        sektor = str(
            bilgi.get("sektor", "")
        ).upper()

        alt = str(
            bilgi.get("alt_sektor", "")
        ).upper()

        if hedef in sektor or hedef in alt:
            sonuc.append(sembol)

    return sorted(set(sonuc))
