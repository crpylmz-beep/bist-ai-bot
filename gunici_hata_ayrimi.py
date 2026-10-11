from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

eski = '''    except Exception:
        return None


def gun_ici_top10_tara():
'''

yeni = '''    except Exception as e:
        hata = str(e).lower()

        if "invalid symbol" in hata:
            return {
                "_durum": "GECERSIZ_SEMBOL",
                "sembol": sembol
            }

        return {
            "_durum": "GECICI_HATA",
            "sembol": sembol,
            "_hata": str(e)
        }


def gun_ici_top10_tara():
'''

if eski not in s:
    raise SystemExit(
        "HATA: Degistirilecek bolum bulunamadi."
    )

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("GUN ICI HATA AYRIMI EKLENDI")