from pathlib import Path
import shutil

p = Path("bist_bot.py")

# Güvenlik yedeği
yedek = Path("bist_bot_gunici_haber_ai_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

s = p.read_text(encoding="utf-8")

# =========================================================
# 1) GUN ICI PUANLAR TAMAMLANDIKTAN SONRA
#    HABER AI ILE SEVIYELERI YENIDEN HESAPLA
# =========================================================

eski = '''        gun_ici_sat_puani = max(
            0, min(100, gun_ici_sat_puani)
        )

        gun_ici_risk = max(
'''

yeni = '''        gun_ici_sat_puani = max(
            0, min(100, gun_ici_sat_puani)
        )

        # =================================================
        # MADDE 44-47
        # GUN ICI DINAMIK HABER ETKILI AI MOTORU
        # =================================================
        gun_ici_haber_ai_aktif = False
        gun_ici_haber_ai_karar = "IZLE"
        gun_ici_haber_fiyat_teyidi = 0.0
        gun_ici_nihai_ai_puan = float(gun_ici_al_puani)
        gun_ici_haber_seviye_etkisi = 0.0

        try:
            gun_ici_haber_ai_aktif = (
                abs(float(haber_puani or 0)) >= 0.5
                and float(haber_guven or 0) >= 25
            )

            if gun_ici_haber_ai_aktif:

                vwap_ai_ustu = (
                    True
                    if fiyat > seans_vwap
                    else False
                )

                obv_ai_pozitif = None

                if obv_durum == "YUKSELEN":
                    obv_ai_pozitif = True
                elif obv_durum == "DUSEN":
                    obv_ai_pozitif = False

                # 5dk ATR varsa onu kullan.
                # Aşırı küçük ATR durumunda gün içi aralık koruma sağlar.
                ai_atr = max(
                    float(atr14_5 or 0),
                    float(gun_aralik or 0) * 0.20,
                    fiyat * 0.002
                )

                ai_sonuc = (
                    haber_etki_motoru.hisse_haber_ai_guncelle(
                        teknik_puan=gun_ici_al_puani,
                        fiyat=fiyat,
                        atr=ai_atr,
                        destek=gun_dusuk,
                        direnc=max(
                            yakin_direnc,
                            gun_yuksek
                        ),
                        haber_puani=haber_puani,
                        haber_guven=haber_guven,
                        sektor_puani=0,
                        makro_puani=0,
                        fiyat_degisim_yuzde=acilisa_gore_degisim,
                        hacim_orani=hacim3_orani,
                        vwap_ustu=vwap_ai_ustu,
                        obv_pozitif=obv_ai_pozitif,
                        piyasa_rejimi=0,
                        haber_dakika=0,
                        ogrenilmis_katsayi=1.0,
                    )
                )

                gun_ici_haber_ai_karar = ai_sonuc.get(
                    "ai_karar",
                    "IZLE"
                )

                gun_ici_haber_fiyat_teyidi = float(
                    ai_sonuc.get(
                        "fiyat_teyidi",
                        0
                    ) or 0
                )

                gun_ici_nihai_ai_puan = float(
                    ai_sonuc.get(
                        "nihai_ai_puan",
                        gun_ici_al_puani
                    ) or gun_ici_al_puani
                )

                gun_ici_haber_seviye_etkisi = float(
                    ai_sonuc.get(
                        "haber_seviye_etkisi",
                        0
                    ) or 0
                )

                # Haber etkisine göre gün içi seviyeleri güncelle.
                alim_alt = float(
                    ai_sonuc.get(
                        "alim_alt",
                        alim_alt
                    )
                )

                alim_ust = float(
                    ai_sonuc.get(
                        "alim_ust",
                        alim_ust
                    )
                )

                kar_al = float(
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

                gun_ici_karar_nedenleri.append(
                    f"Haber AI {float(haber_puani):+.1f}/10 "
                    f"| Guven %{float(haber_guven):.0f} "
                    f"| Nihai AI {gun_ici_nihai_ai_puan:.1f}"
                )

        except Exception as gun_ici_ai_hata:
            gun_ici_haber_ai_aktif = False

        gun_ici_risk = max(
'''

if eski not in s:
    raise SystemExit(
        "GUN ICI AI SEVIYE BAGLAMA NOKTASI BULUNAMADI"
    )

s = s.replace(eski, yeni, 1)


# =========================================================
# 2) TEKNIK KARARDAN SONRA AI NIHАI KARARI
# =========================================================

eski2 = '''        else:
            gun_ici_karar = "IZLE"

        gun_ici_ana_neden = (
'''

yeni2 = '''        else:
            gun_ici_karar = "IZLE"

        # Haber AI yalnız anlamlı haber olduğunda nihai karara müdahale eder.
        if gun_ici_haber_ai_aktif:

            if gun_ici_haber_ai_karar == "GUCLU_AL_ADAYI":
                # Çok güçlü teknik SAT varsa tek haberle tersine çevirmiyoruz.
                if gun_ici_sat_puani < 75:
                    gun_ici_karar = "AL"

            elif gun_ici_haber_ai_karar == "AL":
                if gun_ici_sat_puani < 70:
                    gun_ici_karar = "AL"

            elif gun_ici_haber_ai_karar == "SAT":
                gun_ici_karar = "SAT"

            elif gun_ici_haber_ai_karar == "RISKLI_IZLE":
                if gun_ici_karar == "AL":
                    gun_ici_karar = "IZLE"

        gun_ici_ana_neden = (
'''

if eski2 not in s:
    raise SystemExit(
        "GUN ICI AI KARAR BAGLAMA NOKTASI BULUNAMADI"
    )

s = s.replace(eski2, yeni2, 1)


# =========================================================
# 3) RETURN ICINE AI DETAYLARI
# =========================================================

eski3 = '''            "haber_sinifi": haber_sinifi,
            "gun_ici_karar": gun_ici_karar,
'''

yeni3 = '''            "haber_sinifi": haber_sinifi,

            # MADDE 44-47 - GUN ICI HABER AI
            "gun_ici_haber_ai_aktif": gun_ici_haber_ai_aktif,
            "gun_ici_haber_ai_karar": gun_ici_haber_ai_karar,
            "gun_ici_haber_fiyat_teyidi": round(
                gun_ici_haber_fiyat_teyidi,
                2
            ),
            "gun_ici_nihai_ai_puan": round(
                gun_ici_nihai_ai_puan,
                1
            ),
            "gun_ici_haber_seviye_etkisi": round(
                gun_ici_haber_seviye_etkisi,
                3
            ),

            "gun_ici_karar": gun_ici_karar,
'''

if eski3 not in s:
    raise SystemExit(
        "GUN ICI AI RETURN NOKTASI BULUNAMADI"
    )

s = s.replace(eski3, yeni3, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print(
    "GUN ICI TOP10 HABER AI AL-SAT-STOP BAGLANTISI TAMAM"
)
