from pathlib import Path

p = Path("kap_canli.py")

kod = r'''
import time
import requests
from bs4 import BeautifulSoup
import haber_zeka

KAP_URL = "https://www.kap.org.tr/tr/bildirim-sorgu"

SON_GORULEN = set()


def kap_sayfa_oku():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    r = requests.get(
        KAP_URL,
        headers=headers,
        timeout=15
    )

    r.raise_for_status()

    return r.text


def kap_bildirimleri_bul(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    metin = soup.get_text(
        " ",
        strip=True
    )

    return metin


def kap_kontrol():
    try:
        html = kap_sayfa_oku()
        metin = kap_bildirimleri_bul(html)

        print(
            "KAP BAGLANTISI TAMAM | "
            f"ALINAN KARAKTER: {len(metin)}"
        )

        return True

    except Exception as e:
        print(
            "KAP BAGLANTI HATASI:",
            e
        )

        return False


if __name__ == "__main__":
    kap_kontrol()
'''

p.write_text(
    kod,
    encoding="utf-8"
)

print("KAP CANLI IZLEME TEMELI OLUSTURULDU")
