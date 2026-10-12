from pathlib import Path

p = Path("kap_canli.py")

kod = r'''
import re
import requests
from bs4 import BeautifulSoup
import haber_zeka

KAP_URL = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def kap_sayfa_oku():
    r = requests.get(
        KAP_URL,
        headers=HEADERS,
        timeout=20
    )
    r.raise_for_status()
    return r.text


def sembol_bul(text):
    adaylar = re.findall(
        r"\b[A-Z]{3,6}\b",
        text or ""
    )

    yasak = {
        "BIST", "KAP", "SPK", "MKK",
        "PAY", "AŞ", "AS", "TL"
    }

    for x in adaylar:
        if x not in yasak:
            return x

    return None


def kap_bildirimleri_ayir(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    satirlar = []

    for tr in soup.find_all("tr"):
        hucreler = [
            td.get_text(
                " ",
                strip=True
            )
            for td in tr.find_all("td")
        ]

        if len(hucreler) < 4:
            continue

        tam = " | ".join(hucreler)

        sembol = sembol_bul(tam)

        if not sembol:
            continue

        satirlar.append({
            "sembol": sembol,
            "ham_metin": tam
        })

    return satirlar


def kap_bildirim_isle(kayit):
    sembol = kayit["sembol"]
    metin = kayit["ham_metin"]

    sonuc = haber_zeka.kap_haber_isle(
        sembol=sembol,
        baslik=metin[:180],
        metin=metin,
        kaynak="KAP",
        fiyat_verisi=None
    )

    alarm = sonuc.get(
        "alarm",
        {}
    )

    if alarm.get("alarm"):
        print()
        print(alarm.get("mesaj"))
        print()


def kap_kontrol():
    html = kap_sayfa_oku()

    bildirimler = kap_bildirimleri_ayir(
        html
    )

    print(
        f"KAP BILDIRIM SAYISI: "
        f"{len(bildirimler)}"
    )

    for kayit in bildirimler[:20]:
        print(
            kayit["sembol"],
            "|",
            kayit["ham_metin"][:120]
        )

        kap_bildirim_isle(
            kayit
        )


if __name__ == "__main__":
    kap_kontrol()
'''

p.write_text(
    kod,
    encoding="utf-8"
)

print("KAP PARSER VE AI BAGLANTISI HAZIR")
