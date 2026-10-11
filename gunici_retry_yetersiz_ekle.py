from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

# YETERSIZ_GUNICI_VERI durumunu FILTRE_DISI gibi
# tamamlanmis sayacagiz. Boylece tekrar taranmayacak.

eski = '''                        if durum == "FILTRE_DISI":
                            filtre_disi[sembol] = analiz

                        elif durum == "GECERSIZ_SEMBOL":
'''

yeni = '''                        if durum == "FILTRE_DISI":
                            filtre_disi[sembol] = analiz

                        elif durum == "YETERSIZ_GUNICI_VERI":
                            filtre_disi[sembol] = analiz

                        elif durum == "GECERSIZ_SEMBOL":
'''

if eski not in s:
    raise SystemExit(
        "HATA: Retry durum bolumu bulunamadi."
    )

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("YETERSIZ VERI RETRY DISINA ALINDI")