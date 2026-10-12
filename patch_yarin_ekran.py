from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''        mesaj += (
            f"🏅 {i}. {a.get('sembol', '-')} — {skor}/100\\n"
            f"   💰 {guvenli_float(a.get('fiyat')):.2f} TL "
'''

yeni = '''        mesaj += (
            f"🏅 {i}. {a.get('sembol', '-')} — {skor}/100\\n"
            f"   🧠 Teknik: "
            f"{guvenli_float(a.get('teknik_puan_yarin', skor)):.0f}/100 | "
            f"Haber: {guvenli_float(a.get('haber_puani', 0)):+.1f}/10\\n"
            f"   🤖 Nihai AI: "
            f"{guvenli_float(a.get('nihai_ai_puan', skor)):.0f}/100 | "
            f"{a.get('haber_sinifi', 'NOTR')} | "
            f"Güven %{guvenli_float(a.get('haber_guven', 0)):.0f}\\n"
            f"   💰 {guvenli_float(a.get('fiyat')):.2f} TL "
'''

if eski not in s:
    raise SystemExit("YARIN TOP10 EKRAN BLOKU BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("YARIN TOP10 AI PUAN EKRANI EKLENDI")
