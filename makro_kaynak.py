
from __future__ import annotations
import re

import json
import time
import hashlib
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

import makro_ai


DURUM_DOSYA = Path(
    "webapp/data/makro_kaynak_durum.json"
)

GORULEN_DOSYA = Path(
    "webapp/data/makro_gorulen.json"
)

TCMB_RSS = (
    "https://www.tcmb.gov.tr/wps/wcm/connect/TR/"
    "TCMB+TR/Bottom+Menu/Diger/RSS/Basin+Duyurulari"
)

FED_RSS = (
    "https://www.federalreserve.gov/feeds/"
    "press_monetary.xml"
)

KONTROL_SANIYE = 120


def _load(path, default):
    try:
        if path.exists():
            return json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
    except Exception:
        pass

    return default


def _save(path, veri):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    path.write_text(
        json.dumps(
            veri,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def _id(kaynak, baslik, link):
    ham = (
        str(kaynak)
        + "|"
        + str(baslik)
        + "|"
        + str(link)
    )

    return hashlib.sha1(
        ham.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()[:20]


def rss_oku(url, kaynak):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "BIST-Asistani/1.0"
        )
    }

    r = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    r.raise_for_status()

    root = ET.fromstring(
        r.content
    )

    kayitlar = []

    for item in root.findall(".//item"):

        baslik = (
            item.findtext("title")
            or ""
        ).strip()

        link = (
            item.findtext("link")
            or ""
        ).strip()

        aciklama = (
            item.findtext("description")
            or ""
        ).strip()

        tarih = (
            item.findtext("pubDate")
            or ""
        ).strip()

        if not baslik:
            continue

        kayitlar.append({
            "id": _id(
                kaynak,
                baslik,
                link
            ),
            "kaynak": kaynak,
            "baslik": baslik,
            "metin": aciklama,
            "link": link,
            "tarih": tarih,
        })

    return kayitlar




def tcmb_oku():
    """
    TCMB RSS sayfasi standart RSS XML degil.
    Duyuru basliklarini ve linklerini HTML/metin akisi icinden ayirir.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 BIST-Asistani/1.0"
    }

    r = requests.get(
        TCMB_RSS,
        headers=headers,
        timeout=20
    )

    r.raise_for_status()

    metin = r.text

    # CDATA basliklari
    basliklar = re.findall(
        r"<!\[CDATA\[(.*?)\]\]>",
        metin,
        flags=re.S
    )

    # TCMB duyuru linkleri
    linkler = re.findall(
        r"(/wps/wcm/connect/TR/TCMB\+TR/Main\+Menu/Duyurular/Basin/[^\s<]+)",
        metin
    )

    kayitlar = []

    adet = min(
        len(basliklar),
        len(linkler)
    )

    for i in range(adet):
        baslik = re.sub(
            r"\s+",
            " ",
            basliklar[i]
        ).strip()

        link = linkler[i].strip()

        if not baslik:
            continue

        tam_link = (
            "https://www.tcmb.gov.tr"
            + link
        )

        kayitlar.append({
            "id": _id(
                "TCMB",
                baslik,
                tam_link
            ),
            "kaynak": "TCMB",
            "baslik": baslik,
            "metin": "",
            "link": tam_link,
            "tarih": "",
        })

    return kayitlar


def tum_kaynaklari_oku():

    sonuc = []

    kaynaklar = [
        (
            "TCMB",
            TCMB_RSS
        ),
        (
            "FED",
            FED_RSS
        ),
    ]

    for kaynak, url in kaynaklar:

        try:
            if kaynak == "TCMB":
                kayitlar = tcmb_oku()
            else:
                kayitlar = rss_oku(
                    url,
                    kaynak
                )

            sonuc.extend(
                kayitlar
            )

            print(
                f"{kaynak} RSS | "
                f"{len(kayitlar)} kayit"
            )

        except Exception as e:
            print(
                f"{kaynak} RSS HATA:",
                e
            )

    return sonuc


def yeni_haberleri_isle():

    gorulen = _load(
        GORULEN_DOSYA,
        {
            "ilk_senkron": False,
            "id_listesi": []
        }
    )

    gorulen_set = set(
        gorulen.get(
            "id_listesi",
            []
        )
    )

    haberler = tum_kaynaklari_oku()

    # Ilk calismada eski haberleri yeniden alarm yapma.
    if not gorulen.get(
        "ilk_senkron",
        False
    ):

        for h in haberler:
            gorulen_set.add(
                h["id"]
            )

        _save(
            GORULEN_DOSYA,
            {
                "ilk_senkron": True,
                "id_listesi": list(
                    gorulen_set
                )[-3000:]
            }
        )

        print(
            "MAKRO ILK SENKRON | "
            f"{len(haberler)} mevcut haber hafizaya alindi"
        )

        return 0

    yeniler = [
        h
        for h in haberler
        if h["id"] not in gorulen_set
    ]

    print(
        "MAKRO KONTROL | "
        f"YENI: {len(yeniler)}"
    )

    for h in reversed(
        yeniler
    ):

        print()
        print(
            f"YENI MAKRO HABER | "
            f"{h['kaynak']} | "
            f"{h['baslik']}"
        )

        try:
            sonuc = (
                makro_ai.makro_haber_isle(
                    baslik=h["baslik"],
                    metin=h.get(
                        "metin",
                        ""
                    ),
                    kaynak=h["kaynak"]
                )
            )

            analiz = sonuc.get(
                "analiz",
                {}
            )

            print(
                f"AI | "
                f"{analiz.get('kategori')} | "
                f"{analiz.get('genel_puan', 0):+.1f}"
            )

        except Exception as e:
            print(
                "MAKRO AI ISLEME HATASI:",
                e
            )

        gorulen_set.add(
            h["id"]
        )

    _save(
        GORULEN_DOSYA,
        {
            "ilk_senkron": True,
            "id_listesi": list(
                gorulen_set
            )[-3000:]
        }
    )

    _save(
        DURUM_DOSYA,
        {
            "guncelleme": time.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "toplam_haber": len(
                haberler
            ),
            "yeni_haber": len(
                yeniler
            )
        }
    )

    return len(
        yeniler
    )


def surekli_izle(
    bekleme_saniye=KONTROL_SANIYE
):

    print(
        "MAKRO KAYNAK IZLEME BASLADI | "
        f"{bekleme_saniye} saniyede bir"
    )

    while True:

        try:
            yeni_haberleri_isle()

        except KeyboardInterrupt:
            print()
            print(
                "MAKRO KAYNAK MOTORU DURDU"
            )
            break

        except Exception as e:
            print(
                "MAKRO KAYNAK GENEL HATA:",
                e
            )

        time.sleep(
            bekleme_saniye
        )


if __name__ == "__main__":
    surekli_izle()
