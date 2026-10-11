p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

eski = '''    tahminleri_kaydet(
        sonuclar,
        toplam
    )

    return (
'''

yeni = '''    tahminleri_kaydet(
        sonuclar,
        toplam
    )

    # YARIN TOP10 KAPANIS KILIDI
    # 18:15'ten onceki taramalar kilitli listeyi degistirmez.
    # Ayni gun liste bir kez olusturulduysa tekrar yazilmaz.
    simdi_dt = datetime.now()

    if (
        simdi_dt.weekday() < 5
        and (simdi_dt.hour, simdi_dt.minute) >= (18, 15)
    ):
        mevcut_kilit = yarin_top10_kilitli_oku()
        bugun = simdi_dt.strftime("%Y-%m-%d")

        if (
            not mevcut_kilit
            or mevcut_kilit.get("analiz_tarihi") != bugun
        ):
            yarin_top10_kilitli_kaydet(
                sonuclar,
                toplam
            )
        else:
            print(
                "YARIN TOP10 ZATEN BUGUN KILITLENDI - "
                "LISTE DEGISTIRILMEDI"
            )

    return (
'''

if eski not in s:
    raise SystemExit("BIST_TARA SON BLOGU BULUNAMADI")

s = s.replace(eski, yeni, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 KAPANIS KILIDI EKLENDI")