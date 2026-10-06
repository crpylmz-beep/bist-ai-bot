from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = """    # 100/100 kesinlik algisini engelle
    return max(
        0,
        min(95, round(puan))
    )
"""

yeni = """    # =====================================================
    # HABER / KAP AI KATKISI
    # =====================================================

    teknik_puan = max(
        0,
        min(95, round(puan))
    )

    try:
        haber = haber_zeka.haber_puani_getir(
            a.get("sembol")
        )

        birlesik = haber_zeka.teknik_haber_birlestir(
            teknik_puan,
            haber.get("puan", 0),
            haber.get("guven", 0)
        )

        a["teknik_puan_yarin"] = teknik_puan
        a["haber_puani"] = haber.get("puan", 0)
        a["haber_guven"] = haber.get("guven", 0)
        a["haber_sinifi"] = haber.get("sinif", "NOTR")
        a["nihai_ai_puan"] = birlesik.get(
            "nihai_puan",
            teknik_puan
        )

        return max(
            0,
            min(
                95,
                round(a["nihai_ai_puan"])
            )
        )

    except Exception:
        a["teknik_puan_yarin"] = teknik_puan
        a["haber_puani"] = 0
        a["haber_guven"] = 0
        a["haber_sinifi"] = "NOTR"
        a["nihai_ai_puan"] = teknik_puan
        return teknik_puan
"""

if eski not in s:
    raise SystemExit("HEDEF BLOK BULUNAMADI")

s = s.replace(eski, yeni, 1)
p.write_text(s, encoding="utf-8")

print("YARIN TOP10 HABER AI BAGLANTISI EKLENDI")
