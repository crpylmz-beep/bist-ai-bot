from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

start = s.find("def ozet_mesaji(a):")
end = s.find("\ndef ", start + 10)

if start == -1:
    raise SystemExit("ozet_mesaji BULUNAMADI")

if end == -1:
    end = len(s)

blok = s[start:end]

if "haber_ai = haber_zeka.haber_puani_getir" not in blok:
    hedef = '    durum = a.get("hacimli_kirilim_durum", "BEKLENIYOR")'

    ek = '''    # HABER / KAP AI
    try:
        haber_ai = haber_zeka.haber_puani_getir(a.get("sembol"))
        haber_puani = guvenli_float(haber_ai.get("puan"))
        haber_guven = guvenli_float(haber_ai.get("guven"))
        haber_sinifi = haber_ai.get("sinif", "NOTR")
        haber_adet = int(haber_ai.get("adet", 0) or 0)

        haber_birlesik = haber_zeka.teknik_haber_birlestir(
            a.get("puan", 0),
            haber_puani,
            haber_guven
        )

        haber_nihai_ai = guvenli_float(
            haber_birlesik.get("nihai_puan", a.get("puan", 0))
        )

    except Exception:
        haber_puani = 0
        haber_guven = 0
        haber_sinifi = "NOTR"
        haber_adet = 0
        haber_nihai_ai = guvenli_float(a.get("puan", 0))

'''

    if hedef not in blok:
        raise SystemExit("HABER HESAPLAMA NOKTASI BULUNAMADI")

    blok = blok.replace(hedef, ek + hedef, 1)

if "HABER / KAP AI" not in blok.split("return (",1)[-1]:
    lines = blok.splitlines(True)

    idx = None
    for i, line in enumerate(lines):
        if "ALGOR" in line and "KARARI" in line:
            idx = i
            break

    if idx is None:
        raise SystemExit("ALGORITMA KARARI SATIRI BULUNAMADI")

    ekran = '''        f"📰 HABER / KAP AI\\n"
        f"━━━━━━━━━━━━━━\\n"
        f"Etki: {haber_puani:+.1f}/10\\n"
        f"Sınıf: {haber_sinifi}\\n"
        f"Haber Güveni: %{haber_guven:.0f}\\n"
        f"İzlenen Haber: {haber_adet}\\n"
        f"Teknik Skor: {a.get('puan', 0)}/100\\n"
        f"🤖 Nihai AI Skoru: {haber_nihai_ai:.0f}/100\\n\\n"

'''

    lines.insert(idx, ekran)
    blok = "".join(lines)

s = s[:start] + blok + s[end:]

p.write_text(s, encoding="utf-8")

print("HISSE DETAY HABER AI BASARIYLA EKLENDI")
