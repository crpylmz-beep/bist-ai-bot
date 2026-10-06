from pathlib import Path
import shutil

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

yedek = Path("bist_bot_negatif_etki_koruma_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

# =========================================================
# HISSE DETAY
# =========================================================

eski = '''                karar_hedef = float(
                    haber_ai_sonuc.get(
                        "hedef",
                        karar_hedef
                    )
                )

                karar_stop = float(
                    haber_ai_sonuc.get(
                        "stop",
                        karar_stop
                    )
                )
'''

yeni = '''                eski_karar_hedef = karar_hedef
                eski_karar_stop = karar_stop

                yeni_ai_hedef = float(
                    haber_ai_sonuc.get(
                        "hedef",
                        karar_hedef
                    )
                )

                yeni_ai_stop = float(
                    haber_ai_sonuc.get(
                        "stop",
                        karar_stop
                    )
                )

                toplam_ai_etki = (
                    haber_ai_puani
                    + makro_ai_puani
                    + sektor_ai_puani
                )

                # Negatif etki hedefi yukari tasiyamaz,
                # stopu da daha genis hale getiremez.
                if toplam_ai_etki < 0:
                    karar_hedef = min(
                        eski_karar_hedef,
                        yeni_ai_hedef
                    )

                    karar_stop = max(
                        eski_karar_stop,
                        yeni_ai_stop
                    )
                else:
                    karar_hedef = yeni_ai_hedef
                    karar_stop = yeni_ai_stop
'''

if eski not in s:
    raise SystemExit("HISSE DETAY HEDEF/STOP BLOKU BULUNAMADI")

s = s.replace(eski, yeni, 1)


# =========================================================
# GUN ICI
# =========================================================

eski2 = '''                kar_al = float(
                    ai_sonuc.get(
                        "hedef",
                        kar_al
                    )
                )

                stop = float(
                    ai_sonuc.get(
                        "stop",
                        stop
                    )
                )
'''

yeni2 = '''                eski_kar_al = kar_al
                eski_stop = stop

                yeni_ai_hedef = float(
                    ai_sonuc.get(
                        "hedef",
                        kar_al
                    )
                )

                yeni_ai_stop = float(
                    ai_sonuc.get(
                        "stop",
                        stop
                    )
                )

                toplam_ai_etki = (
                    float(haber_puani or 0)
                    + makro_ai_puani
                    + sektor_ai_puani
                )

                if toplam_ai_etki < 0:
                    kar_al = min(
                        eski_kar_al,
                        yeni_ai_hedef
                    )

                    stop = max(
                        eski_stop,
                        yeni_ai_stop
                    )
                else:
                    kar_al = yeni_ai_hedef
                    stop = yeni_ai_stop
'''

if eski2 not in s:
    raise SystemExit("GUN ICI HEDEF/STOP BLOKU BULUNAMADI")

s = s.replace(eski2, yeni2, 1)


# =========================================================
# YARIN TOP10
# =========================================================

eski3 = '''                a["ai_yarin_hedef"] = guvenli_float(
                    ai_sonuc.get(
                        "hedef",
                        a["ai_yarin_hedef"]
                    )
                )

                a["ai_yarin_stop"] = guvenli_float(
                    ai_sonuc.get(
                        "stop",
                        a["ai_yarin_stop"]
                    )
                )
'''

yeni3 = '''                eski_ai_hedef = a["ai_yarin_hedef"]
                eski_ai_stop = a["ai_yarin_stop"]

                yeni_ai_hedef = guvenli_float(
                    ai_sonuc.get(
                        "hedef",
                        eski_ai_hedef
                    )
                )

                yeni_ai_stop = guvenli_float(
                    ai_sonuc.get(
                        "stop",
                        eski_ai_stop
                    )
                )

                toplam_ai_etki = (
                    haber_puani_ai
                    + makro_ai_puani
                    + sektor_ai_puani
                )

                if toplam_ai_etki < 0:
                    a["ai_yarin_hedef"] = min(
                        eski_ai_hedef,
                        yeni_ai_hedef
                    )

                    a["ai_yarin_stop"] = max(
                        eski_ai_stop,
                        yeni_ai_stop
                    )
                else:
                    a["ai_yarin_hedef"] = yeni_ai_hedef
                    a["ai_yarin_stop"] = yeni_ai_stop
'''

if eski3 not in s:
    raise SystemExit("YARIN TOP10 HEDEF/STOP BLOKU BULUNAMADI")

s = s.replace(eski3, yeni3, 1)

p.write_text(s, encoding="utf-8")

print("NEGATIF AI ETKI HEDEF-STOP KORUMASI TAMAM")
