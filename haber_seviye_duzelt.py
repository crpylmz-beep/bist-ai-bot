from pathlib import Path
import shutil

p = Path("haber_etki_motoru.py")
s = p.read_text(encoding="utf-8")

yedek = Path("haber_etki_motoru_seviye_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

eski = '''    # STOP
    stop_katsayi = 1.35
    if etki < 0:
        stop_katsayi = 1.05
    elif etki > 0.35:
        stop_katsayi = 1.55

    stop = max(
        fiyat - atr * stop_katsayi,
        destek - atr * 0.35
    )

    # HEDEF
    hedef_katsayi = 1.8 + max(0, etki) * 1.2
    if etki < 0:
        hedef_katsayi = 1.35

    hedef = fiyat + atr * hedef_katsayi

    if direnc > fiyat:
        if etki < 0.25:
            hedef = min(hedef, direnc)
        else:
            hedef = min(
                hedef,
                direnc + atr * 0.75
            )
'''

yeni = '''    # STOP
    # Negatif haber/makroda stop daha yakina gelir.
    # Pozitif teyitte ise makul miktarda alan taninir.
    stop_katsayi = 1.25

    if etki <= -0.35:
        stop_katsayi = 0.80
    elif etki < 0:
        stop_katsayi = 1.00
    elif etki >= 0.35:
        stop_katsayi = 1.45

    teknik_stop = fiyat - atr * stop_katsayi

    # Destek cok uzaktaysa stopun gereksiz genislemesine izin verme.
    destek_stop = destek - atr * 0.20

    stop = max(
        0,
        max(
            teknik_stop,
            destek_stop
        )
    )

    # HEDEF
    # Negatif etkide hedef daralir.
    # Pozitif etkide kontrollu genisler.
    if etki <= -0.35:
        hedef_katsayi = 0.85
    elif etki < 0:
        hedef_katsayi = 1.15
    else:
        hedef_katsayi = 1.70 + etki * 0.90

    hedef = fiyat + atr * hedef_katsayi

    if direnc > fiyat:
        if etki < 0:
            hedef = min(
                hedef,
                direnc,
                fiyat + atr * 1.20
            )
        elif etki < 0.25:
            hedef = min(
                hedef,
                direnc
            )
        else:
            hedef = min(
                hedef,
                direnc + atr * 0.60
            )
'''

if eski not in s:
    raise SystemExit("DINAMIK SEVIYE BLOKU BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")

print("NEGATIF HABER/MAKRO HEDEF-STOP MANTIGI DUZELTILDI")
