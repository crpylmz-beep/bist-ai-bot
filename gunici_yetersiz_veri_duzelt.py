from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''        if bugun.empty or len(bugun) < 3:
            return None
'''

yeni = '''        if bugun.empty or len(bugun) < 3:
            return {
                "_durum": "YETERSIZ_GUNICI_VERI",
                "sembol": sembol,
                "_mum_sayisi": len(bugun),
                "_son_veri_tarihi": str(veri.index[-1])
            }
'''

if eski not in s:
    raise SystemExit(
        "HATA: Yetersiz gun ici veri bolumu bulunamadi."
    )

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("YETERSIZ GUN ICI VERI AYRIMI EKLENDI")