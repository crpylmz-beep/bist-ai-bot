from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''        if acilisa_gore_degisim <= -7:
            return None

        if acilisa_gore_degisim >= 9.5:
            return None
'''

yeni = '''        if acilisa_gore_degisim <= -7:
            return {
                "_durum": "FILTRE_DISI",
                "sembol": sembol,
                "_neden": "SERT_EKSI",
                "fiyat": fiyat,
                "acilisa_gore_degisim": acilisa_gore_degisim
            }

        if acilisa_gore_degisim >= 9.5:
            return {
                "_durum": "FILTRE_DISI",
                "sembol": sembol,
                "_neden": "SERT_ARTI",
                "fiyat": fiyat,
                "acilisa_gore_degisim": acilisa_gore_degisim
            }
'''

if eski not in s:
    raise SystemExit(
        "HATA: Risk filtresi bulunamadi."
    )

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("GUN ICI FILTRE DURUMU DUZELTILDI")