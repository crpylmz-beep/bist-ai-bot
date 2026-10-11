p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

hedef = '''    return top10, sonuclar, toplam

def gun_ici_top10_mesaji():
'''

if hedef not in s:
    hedef = '''    return top10, sonuclar, toplam


def gun_ici_top10_mesaji():
'''

if hedef not in s:
    raise SystemExit("GUN ICI RETURN BLOGU BULUNAMADI")

yeni = '''    # -------------------------------------------------
    # KILITLI YARIN TOP10 HACIMLI KIRILIM TAKIBI
    # -------------------------------------------------
    # Burasi sadece kilitli listedeki canli kirilim durumunu
    # ve ilk gerceklesme saatini gunceller.
    # Sira, puan ve islem seviyeleri DEGISTIRILMEZ.
    try:
        kilitli_yarin = yarin_top10_kilitli_oku()

        if kilitli_yarin and isinstance(
            kilitli_yarin.get("top10"),
            list
        ):
            degisiklik_var = False

            for hisse in kilitli_yarin["top10"]:
                sembol = hisse.get("sembol")

                if not sembol:
                    continue

                mum_verisi = veri_map.get(sembol)

                if mum_verisi is None or mum_verisi.empty:
                    continue

                kirilim_seviyesi = guvenli_float(
                    hisse.get("yarin_kirilim")
                )

                ilk_saat, yeni_durum = ilk_hacimli_kirilim_bul(
                    mum_verisi,
                    kirilim_seviyesi
                )

                eski_saat = hisse.get(
                    "ilk_hacimli_kirilim_saati"
                )

                eski_durum = hisse.get(
                    "hacimli_kirilim_durum",
                    "BEKLENIYOR"
                )

                # Ilk gerceklesme saati bir kez bulunduysa
                # daha sonraki taramalarda ASLA degistirilmez.
                if eski_saat:
                    if eski_durum != "GERCEKLESTI":
                        hisse["hacimli_kirilim_durum"] = "GERCEKLESTI"
                        degisiklik_var = True
                    continue

                if ilk_saat:
                    hisse["ilk_hacimli_kirilim_saati"] = ilk_saat
                    hisse["hacimli_kirilim_durum"] = "GERCEKLESTI"
                    degisiklik_var = True

                elif yeni_durum != eski_durum:
                    hisse["hacimli_kirilim_durum"] = yeni_durum
                    degisiklik_var = True

            if degisiklik_var:
                with open(
                    YARIN_TOP10_FILE,
                    "w",
                    encoding="utf-8"
                ) as f:
                    json.dump(
                        kilitli_yarin,
                        f,
                        ensure_ascii=False,
                        indent=2,
                        default=str
                    )

                print(
                    "YARIN TOP10 KIRILIM TAKIBI GUNCELLENDI"
                )
            else:
                print(
                    "YARIN TOP10 KIRILIM TAKIBI: "
                    "YENI DEGISIKLIK YOK"
                )

    except Exception as e:
        print(
            "YARIN TOP10 KIRILIM TAKIP HATASI:",
            e
        )

    return top10, sonuclar, toplam


def gun_ici_top10_mesaji():
'''

s = s.replace(hedef, yeni, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 5DK KIRILIM TAKIBI EKLENDI")