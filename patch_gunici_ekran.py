from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''            (
                f"{sira}. {a['sembol']} — "
                f"{a['gun_ici_puan']:.0f}/100"
            ),
            (
                f"   💰 {a['fiyat']:.2f} TL | "
'''

yeni = '''            (
                f"{sira}. {a['sembol']} — "
                f"{a['gun_ici_puan']:.0f}/100"
            ),
            (
                f"   🧠 Teknik: "
                f"{a.get('teknik_gun_ici_puan', a['gun_ici_puan']):.0f}/100 | "
                f"Haber: {a.get('haber_puani', 0):+.1f}/10"
            ),
            (
                f"   🤖 Nihai AI: "
                f"{a.get('gun_ici_puan', 0):.0f}/100 | "
                f"{a.get('haber_sinifi', 'NOTR')} | "
                f"Güven %{a.get('haber_guven', 0):.0f}"
            ),
            (
                f"   💰 {a['fiyat']:.2f} TL | "
'''

if eski not in s:
    raise SystemExit("EKRAN BLOKU BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("GUN ICI AI PUAN EKRANI EKLENDI")
