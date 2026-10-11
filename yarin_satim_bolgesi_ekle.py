p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

eski = '''        # Ilk kisa vadeli kar alma seviyesi kirilimdan bagimsizdir.
        yarin_kar_al = fiyat + atr14 * 0.50

        # Kisa vadeli stop.
'''

yeni = '''        # Ilk kisa vadeli kar alma seviyesi kirilimdan bagimsizdir.
        yarin_kar_al = fiyat + atr14 * 0.50

        # Yarin icin dinamik satim bolgesi.
        # ATR ve yakin teknik direnc birlikte dikkate alinir.
        yarin_satim_alt = max(
            yarin_kar_al,
            fiyat + atr14 * 0.40
        )

        yarin_satim_ust = max(
            yarin_satim_alt,
            min(
                yarin_kirilim,
                fiyat + atr14 * 0.80
            )
        )

        # Kisa vadeli stop.
'''

if eski not in s:
    raise SystemExit("HESAPLAMA BLOGU BULUNAMADI")

s = s.replace(eski, yeni, 1)

eski2 = '''            "yarin_kar_al": yarin_kar_al,
            "yarin_stop": yarin_stop,
'''

yeni2 = '''            "yarin_kar_al": yarin_kar_al,
            "yarin_satim_alt": yarin_satim_alt,
            "yarin_satim_ust": yarin_satim_ust,
            "yarin_stop": yarin_stop,
'''

if eski2 not in s:
    raise SystemExit("SONUC BLOGU BULUNAMADI")

s = s.replace(eski2, yeni2, 1)

with open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(s)

print("YARIN SATIM BOLGESI EKLENDI")