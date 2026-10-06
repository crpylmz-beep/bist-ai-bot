from pathlib import Path
import shutil

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

yedek = Path("bist_bot_makro_tetik_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

# =========================================================
# HISSE DETAY: HABER VEYA MAKRO VARSA AI AKTIF
# =========================================================

eski = '''            haber_ai_aktif = (
                abs(haber_ai_puani) >= 0.5
                and haber_ai_guven >= 25
            )

            if haber_ai_aktif:
'''

yeni = '''            makro_canli = canli_makro_puani_getir(
                sembol
            )

            makro_ai_puani = guvenli_float(
                makro_canli.get("makro_puani")
            )

            sektor_ai_puani = guvenli_float(
                makro_canli.get("sektor_puani")
            )

            haber_ai_aktif = (
                (
                    abs(haber_ai_puani) >= 0.5
                    and haber_ai_guven >= 25
                )
                or abs(makro_ai_puani) >= 0.5
                or abs(sektor_ai_puani) >= 0.5
            )

            if haber_ai_aktif:
'''

if eski not in s:
    raise SystemExit("HISSE DETAY MAKRO TETIK NOKTASI BULUNAMADI")

s = s.replace(eski, yeni, 1)


# =========================================================
# GUN ICI: HABER VEYA MAKRO VARSA AI AKTIF
# =========================================================

eski2 = '''            gun_ici_haber_ai_aktif = (
                abs(float(haber_puani or 0)) >= 0.5
                and float(haber_guven or 0) >= 25
            )

            if gun_ici_haber_ai_aktif:
'''

yeni2 = '''            makro_canli = canli_makro_puani_getir(
                sembol
            )

            makro_ai_puani = guvenli_float(
                makro_canli.get("makro_puani")
            )

            sektor_ai_puani = guvenli_float(
                makro_canli.get("sektor_puani")
            )

            gun_ici_haber_ai_aktif = (
                (
                    abs(float(haber_puani or 0)) >= 0.5
                    and float(haber_guven or 0) >= 25
                )
                or abs(makro_ai_puani) >= 0.5
                or abs(sektor_ai_puani) >= 0.5
            )

            if gun_ici_haber_ai_aktif:
'''

if eski2 not in s:
    raise SystemExit("GUN ICI MAKRO TETIK NOKTASI BULUNAMADI")

s = s.replace(eski2, yeni2, 1)


# =========================================================
# YARIN TOP10: HABER VEYA MAKRO VARSA AI AKTIF
# =========================================================

eski3 = '''            haber_ai_aktif = (
                abs(haber_puani_ai) >= 0.5
                and haber_guven_ai >= 25
            )

            a["yarin_haber_ai_aktif"] = haber_ai_aktif

            if haber_ai_aktif:
'''

yeni3 = '''            makro_canli = canli_makro_puani_getir(
                a.get("sembol")
            )

            makro_ai_puani = guvenli_float(
                makro_canli.get("makro_puani")
            )

            sektor_ai_puani = guvenli_float(
                makro_canli.get("sektor_puani")
            )

            haber_ai_aktif = (
                (
                    abs(haber_puani_ai) >= 0.5
                    and haber_guven_ai >= 25
                )
                or abs(makro_ai_puani) >= 0.5
                or abs(sektor_ai_puani) >= 0.5
            )

            a["yarin_haber_ai_aktif"] = haber_ai_aktif

            if haber_ai_aktif:
'''

if eski3 not in s:
    raise SystemExit("YARIN TOP10 MAKRO TETIK NOKTASI BULUNAMADI")

s = s.replace(eski3, yeni3, 1)

p.write_text(s, encoding="utf-8")

print("MAKRO TEK BASINA AI MOTORUNU TETIKLIYOR")
