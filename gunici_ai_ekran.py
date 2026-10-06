from pathlib import Path
import shutil

p = Path("bist_bot.py")

yedek = Path("bist_bot_gunici_ekran_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

s = p.read_text(encoding="utf-8")

eski = '''            (
                f"   🤖 Nihai AI: "
                f"{a.get('gun_ici_puan', 0):.0f}/100 | "
                f"{a.get('haber_sinifi', 'NOTR')} | "
                f"Güven %{a.get('haber_guven', 0):.0f}"
            ),
            (
                f"   💰 {a['fiyat']:.2f} TL | "
'''

yeni = '''            (
                f"   🤖 Nihai AI: "
                f"{a.get('gun_ici_nihai_ai_puan', a.get('gun_ici_puan', 0)):.0f}/100 | "
                f"{a.get('haber_sinifi', 'NOTR')} | "
                f"Güven %{a.get('haber_guven', 0):.0f}"
            ),
            (
                f"   🧭 AI Kararı: "
                f"{a.get('gun_ici_haber_ai_karar', a.get('gun_ici_karar', 'IZLE'))} | "
                f"Fiyat Teyidi "
                f"{a.get('gun_ici_haber_fiyat_teyidi', 0):+.1f}"
            ),
            (
                f"   🎯 Alım Bölgesi: "
                f"{a.get('gun_ici_alim_alt', 0):.2f} - "
                f"{a.get('gun_ici_alim_ust', 0):.2f} TL"
            ),
            (
                f"   💵 Hedef: "
                f"{a.get('gun_ici_kar_al', 0):.2f} TL | "
                f"🛑 Stop: "
                f"{a.get('gun_ici_stop', 0):.2f} TL"
            ),
            (
                f"   💰 {a['fiyat']:.2f} TL | "
'''

if eski not in s:
    raise SystemExit("GUN ICI EKRAN BAGLAMA NOKTASI BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("GUN ICI TOP10 AI DETAY EKRANI TAMAM")
