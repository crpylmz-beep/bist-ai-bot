from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

# 1) ozet_mesaji icinde haber bilgisini hesapla
eski1 = '''    macd_y = macd_yorumu(a["macd"], a["signal"], a["hist"])

    durum = a.get("hacimli_kirilim_durum", "BEKLENIYOR")
'''

yeni1 = '''    macd_y = macd_yorumu(a["macd"], a["signal"], a["hist"])

    # =====================================================
    # HABER / KAP AI ANALIZI
    # =====================================================
    try:
        haber_ai = haber_zeka.haber_puani_getir(
            a.get("sembol")
        )
        haber_puani = guvenli_float(
            haber_ai.get("puan")
        )
        haber_guven = guvenli_float(
            haber_ai.get("guven")
        )
        haber_sinifi = haber_ai.get(
            "sinif",
            "NOTR"
        )
        haber_adet = int(
            haber_ai.get("adet", 0) or 0
        )
    except Exception:
        haber_puani = 0
        haber_guven = 0
        haber_sinifi = "NOTR"
        haber_adet = 0

    try:
        haber_birlesik = haber_zeka.teknik_haber_birlestir(
            a.get("puan", 0),
            haber_puani,
            haber_guven
        )
        haber_nihai_ai = guvenli_float(
            haber_birlesik.get(
                "nihai_puan",
                a.get("puan", 0)
            )
        )
    except Exception:
        haber_nihai_ai = guvenli_float(
            a.get("puan", 0)
        )

    durum = a.get("hacimli_kirilim_durum", "BEKLENIYOR")
'''

if eski1 not in s:
    raise SystemExit("HABER HESAPLAMA EKLEME NOKTASI BULUNAMADI")

s = s.replace(eski1, yeni1, 1)

# 2) ekrana Haber/KAP AI bolumu ekle
eski2 = '''        f"{kirilim_yazi}\\n\\n"

        f"🧠 ALGORİTMA KARARI\\n"
'''

yeni2 = '''        f"{kirilim_yazi}\\n\\n"

        f"📰 HABER / KAP AI\\n"
        f"━━━━━━━━━━━━━━\\n"
        f"Etki: {haber_puani:+.1f}/10\\n"
        f"Sınıf: {haber_sinifi}\\n"
        f"Haber Güveni: %{haber_guven:.0f}\\n"
        f"İzlenen Haber: {haber_adet}\\n"
        f"Teknik Skor: {a.get('puan', 0)}/100\\n"
        f"🤖 Nihai AI Skoru: {haber_nihai_ai:.0f}/100\\n\\n"

        f"🧠 ALGORİTMA KARARI\\n"
'''

if eski2 not in s:
    raise SystemExit("HABER AI EKRAN EKLEME NOKTASI BULUNAMADI")

s = s.replace(eski2, yeni2, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("HISSE OZETI HABER KAP AI EKLENDI")
