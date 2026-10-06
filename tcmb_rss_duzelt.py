from pathlib import Path
import re

p = Path("makro_kaynak.py")
s = p.read_text(encoding="utf-8")

# TCMB parser fonksiyonu ekle
if "def tcmb_oku(" not in s:
    ek = r'''

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
'''
    idx = s.find("def tum_kaynaklari_oku():")
    if idx == -1:
        raise SystemExit("tum_kaynaklari_oku BULUNAMADI")
    s = s[:idx] + ek + "\n\n" + s[idx:]

# kaynak okuma kısmını TCMB için özel hale getir
eski = '''    for kaynak, url in kaynaklar:

        try:
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
'''

yeni = '''    for kaynak, url in kaynaklar:

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
'''

if eski not in s:
    raise SystemExit("KAYNAK DONGUSU BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("TCMB OZEL RSS PARSER EKLENDI")
