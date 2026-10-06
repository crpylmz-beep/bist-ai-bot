from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

bas = s.find("def gun_ici_analiz_hesapla")
son = s.find("\ndef ", bas + 10)

if bas == -1:
    raise SystemExit("GUN ICI ANALIZ FONKSIYONU BULUNAMADI")

if son == -1:
    son = len(s)

parca = s[bas:son]

hedef = """        puan = max(
            0,
            min(100, puan)
        )
"""

ek = """        puan = max(
            0,
            min(100, puan)
        )

        # =================================================
        # GUN ICI HABER / KAP AI KATKISI
        # =================================================
        teknik_gun_ici_puan = puan

        try:
            haber = haber_zeka.haber_puani_getir(sembol)

            birlesik = haber_zeka.teknik_haber_birlestir(
                teknik_gun_ici_puan,
                haber.get("puan", 0),
                haber.get("guven", 0)
            )

            puan = birlesik.get(
                "nihai_puan",
                teknik_gun_ici_puan
            )

            haber_puani = haber.get("puan", 0)
            haber_guven = haber.get("guven", 0)
            haber_sinifi = haber.get("sinif", "NOTR")

        except Exception:
            puan = teknik_gun_ici_puan
            haber_puani = 0
            haber_guven = 0
            haber_sinifi = "NOTR"
"""

if hedef not in parca:
    raise SystemExit("GUN ICI PUAN BLOKU BULUNAMADI")

parca = parca.replace(hedef, ek, 1)

eski_return = '''            "gun_ici_puan": puan,
'''

yeni_return = '''            "gun_ici_puan": puan,
            "teknik_gun_ici_puan": teknik_gun_ici_puan,
            "haber_puani": haber_puani,
            "haber_guven": haber_guven,
            "haber_sinifi": haber_sinifi,
'''

if eski_return not in parca:
    raise SystemExit("GUN ICI RETURN BLOKU BULUNAMADI")

parca = parca.replace(
    eski_return,
    yeni_return,
    1
)

s = s[:bas] + parca + s[son:]

p.write_text(
    s,
    encoding="utf-8"
)

print("GUN ICI TOP10 HABER AI BAGLANTISI EKLENDI")
