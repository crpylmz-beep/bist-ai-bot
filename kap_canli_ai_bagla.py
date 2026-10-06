from pathlib import Path
import shutil

# =========================================================
# 1) CANLI MOTOR: ONCELIKLI HISSE GUNCELLEME
# =========================================================

p = Path("canli_motor.py")
s = p.read_text(encoding="utf-8")

yedek = Path("canli_motor_kap_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

if "def oncelikli_hisse_guncelle(" not in s:

    ek = r'''

# =========================================================
# KAP / HABER ONCELIKLI HISSE GUNCELLEME
# =========================================================

def oncelikli_hisse_guncelle(
    sembol,
    gun_ici_yenile=True
):
    """
    Yeni KAP/haber gelen hisseyi genel BIST turunu beklemeden
    aninda yeniden analiz eder ve Hisse Ara verisine yazar.
    """

    sembol = str(sembol or "").strip().upper()

    if not sembol:
        return None

    print(
        f"ONCELIKLI AI ANALIZ | {sembol} | {simdi()}"
    )

    try:
        sonuc = bist_bot.hisse_analiz_hesapla(
            sembol,
            period="6mo"
        )

        if not sonuc:
            print(
                f"ONCELIKLI ANALIZ VERI YOK | {sembol}"
            )
            return None

        # Web ekraninda kullanılan ek sinyal alanlari.
        try:
            sonuc["sinyal"] = bist_bot.sinyal_sinifi(
                sonuc
            )
        except Exception:
            pass

        try:
            sonuc["guclu_tepki"] = (
                bist_bot.guclu_tepki_mi(
                    sonuc
                )
            )
        except Exception:
            sonuc["guclu_tepki"] = False

        try:
            sonuc["tepki_puani"] = (
                bist_bot.tepki_puani(sonuc)
                if sonuc.get("guclu_tepki")
                else 0
            )
        except Exception:
            sonuc["tepki_puani"] = 0

        sonuc["analiz_durumu"] = "HAZIR"
        sonuc["canli_guncelleme"] = simdi()
        sonuc["oncelikli_guncelleme"] = True

        data_file = Path(
            getattr(
                bist_bot,
                "DATA_FILE",
                "webapp/data/bist_veri.json"
            )
        )

        mevcut = {
            "guncelleme": simdi(),
            "bist100": {},
            "hisseler": []
        }

        if data_file.exists():
            try:
                mevcut = json.loads(
                    data_file.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception:
                pass

        hisseler = mevcut.get(
            "hisseler",
            []
        )

        if not isinstance(hisseler, list):
            hisseler = []

        yeni_liste = []
        bulundu = False

        for h in hisseler:

            if not isinstance(h, dict):
                continue

            kod = str(
                h.get("sembol", "")
            ).strip().upper()

            if kod == sembol:
                yeni_liste.append(
                    dict(sonuc)
                )
                bulundu = True
            else:
                yeni_liste.append(h)

        if not bulundu:
            yeni_liste.append(
                dict(sonuc)
            )

        yeni_liste.sort(
            key=lambda x: str(
                x.get("sembol", "")
            ).upper()
        )

        mevcut["hisseler"] = yeni_liste
        mevcut["guncelleme"] = simdi()

        data_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        gecici = data_file.with_suffix(
            data_file.suffix + ".tmp"
        )

        gecici.write_text(
            json.dumps(
                mevcut,
                ensure_ascii=False,
                indent=2,
                default=str
            ),
            encoding="utf-8"
        )

        gecici.replace(data_file)

        durum_yaz(
            son_oncelikli_hisse=sembol,
            son_oncelikli_guncelleme=simdi()
        )

        print(
            f"HISSE ARA ANLIK GUNCELLENDI | {sembol}"
        )

        # Yeni haber Gün İçi aday sıralamasını da değiştirebilir.
        if gun_ici_yenile:
            try:
                gun_ici_top10_guncelle()
            except Exception as e:
                print(
                    "KAP SONRASI GUN ICI YENILEME HATASI:",
                    e
                )

        return sonuc

    except Exception as e:
        print(
            f"ONCELIKLI HISSE HATASI | {sembol}:",
            e
        )
        return None
'''

    s += ek
    p.write_text(
        s,
        encoding="utf-8"
    )

print("CANLI MOTOR ONCELIKLI HISSE MODULU TAMAM")


# =========================================================
# 2) KAP CANLI: YENI HABERDEN SONRA TETIKLE
# =========================================================

p = Path("kap_canli.py")
s = p.read_text(encoding="utf-8")

yedek = Path("kap_canli_ai_tetik_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

if "import canli_motor" not in s:
    s = s.replace(
        "import haber_zeka",
        "import haber_zeka\nimport canli_motor",
        1
    )

eski = '''        web_alarm_kaydet(
            analiz,
            alarm
        )
'''

yeni = '''        web_alarm_kaydet(
            analiz,
            alarm
        )

    # =====================================================
    # MADDE 48 - KAP GELEN HISSEYI ANINDA YENIDEN ANALIZ ET
    # Alarm cikmasa bile haber ilgili hissenin AI skorunu
    # ve AL / SAT / STOP seviyelerini etkileyebilir.
    # =====================================================
    if sembol:
        try:
            canli_motor.oncelikli_hisse_guncelle(
                sembol,
                gun_ici_yenile=True
            )
        except Exception as e:
            print(
                "KAP AI HISSE TETIK HATASI:",
                e
            )
'''

if "MADDE 48 - KAP GELEN HISSEYI ANINDA" not in s:
    if eski not in s:
        raise SystemExit(
            "KAP TETIK BAGLAMA NOKTASI BULUNAMADI"
        )

    s = s.replace(
        eski,
        yeni,
        1
    )

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP -> CANLI HISSE AI TETIGI TAMAM")
