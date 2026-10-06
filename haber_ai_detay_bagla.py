from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

# ---------------------------------------------------------
# IMPORT
# ---------------------------------------------------------
if "import haber_etki_motoru" not in s:
    if "import haber_zeka" in s:
        s = s.replace(
            "import haber_zeka",
            "import haber_zeka\nimport haber_etki_motoru",
            1
        )
    else:
        s = "import haber_etki_motoru\n" + s


# ---------------------------------------------------------
# HABER AI SEVIYE MOTORUNU KARAR MOTORUNA BAGLA
# ---------------------------------------------------------
eski = '''        karar_giris_alt = yarin_alim_alt
        karar_giris_ust = yarin_alim_ust
        karar_hedef = yarin_kar_al
        karar_stop = yarin_stop

        karar_risk = max(
'''

yeni = '''        karar_giris_alt = yarin_alim_alt
        karar_giris_ust = yarin_alim_ust
        karar_hedef = yarin_kar_al
        karar_stop = yarin_stop

        # =====================================================
        # MADDE 44-47 - HABER ETKILI DINAMIK AI KARAR MOTORU
        # =====================================================
        haber_ai_puani = 0.0
        haber_ai_guven = 0.0
        haber_ai_sinifi = "NOTR"
        haber_ai_karar = "IZLE"
        haber_fiyat_teyidi = 0.0
        haber_nihai_ai_puan = float(al_puani)
        haber_seviye_etkisi = 0.0
        haber_ai_aktif = False

        try:
            haber_bilgi = haber_zeka.haber_puani_getir(sembol) or {}

            if isinstance(haber_bilgi, dict):
                haber_ai_puani = float(
                    haber_bilgi.get(
                        "puan",
                        haber_bilgi.get(
                            "haber_puani",
                            haber_bilgi.get("etki_puani", 0)
                        )
                    ) or 0
                )

                haber_ai_guven = float(
                    haber_bilgi.get(
                        "guven",
                        haber_bilgi.get(
                            "haber_guven",
                            haber_bilgi.get("guven_skoru", 0)
                        )
                    ) or 0
                )

                haber_ai_sinifi = str(
                    haber_bilgi.get(
                        "sinif",
                        haber_bilgi.get(
                            "haber_sinifi",
                            haber_bilgi.get("etki_sinifi", "NOTR")
                        )
                    ) or "NOTR"
                )

            elif isinstance(haber_bilgi, (int, float)):
                haber_ai_puani = float(haber_bilgi)

            # Sadece anlamli haber teknik seviyeleri etkilesin.
            haber_ai_aktif = (
                abs(haber_ai_puani) >= 0.5
                and haber_ai_guven >= 25
            )

            if haber_ai_aktif:
                vwap_ai_ustu = None

                if vwap20_durum == "USTUNDE":
                    vwap_ai_ustu = True
                elif vwap20_durum == "ALTINDA":
                    vwap_ai_ustu = False

                direnc_ai = locals().get(
                    "direnÃ§",
                    fiyat + atr14 * 2
                )

                haber_ai_sonuc = (
                    haber_etki_motoru.hisse_haber_ai_guncelle(
                        teknik_puan=al_puani,
                        fiyat=fiyat,
                        atr=atr14,
                        destek=destek,
                        direnc=direnc_ai,
                        haber_puani=haber_ai_puani,
                        haber_guven=haber_ai_guven,
                        sektor_puani=0,
                        makro_puani=0,
                        fiyat_degisim_yuzde=gunluk_degisim,
                        hacim_orani=hacim_orani,
                        vwap_ustu=vwap_ai_ustu,
                        obv_pozitif=None,
                        piyasa_rejimi=0,
                        haber_dakika=0,
                        ogrenilmis_katsayi=1.0,
                    )
                )

                haber_ai_karar = haber_ai_sonuc.get(
                    "ai_karar",
                    "IZLE"
                )

                haber_fiyat_teyidi = float(
                    haber_ai_sonuc.get(
                        "fiyat_teyidi",
                        0
                    ) or 0
                )

                haber_nihai_ai_puan = float(
                    haber_ai_sonuc.get(
                        "nihai_ai_puan",
                        al_puani
                    ) or al_puani
                )

                haber_seviye_etkisi = float(
                    haber_ai_sonuc.get(
                        "haber_seviye_etkisi",
                        0
                    ) or 0
                )

                # Haber etkili yeni ALIM / HEDEF / STOP
                karar_giris_alt = float(
                    haber_ai_sonuc.get(
                        "alim_alt",
                        karar_giris_alt
                    )
                )

                karar_giris_ust = float(
                    haber_ai_sonuc.get(
                        "alim_ust",
                        karar_giris_ust
                    )
                )

                karar_hedef = float(
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

                karar_nedenleri.append(
                    f"Haber AI: {haber_ai_puani:+.1f}/10 "
                    f"| Guven %{haber_ai_guven:.0f} "
                    f"| Nihai AI {haber_nihai_ai_puan:.1f}"
                )

        except Exception as haber_ai_hata:
            # Haber motorundaki gecici hata teknik motoru durdurmasin.
            haber_ai_aktif = False

        karar_risk = max(
'''

if eski not in s:
    raise SystemExit("HABER AI BAGLAMA NOKTASI BULUNAMADI")

s = s.replace(eski, yeni, 1)


# ---------------------------------------------------------
# TEKNIK KARARDAN SONRA AI KARARINI UYGULA
# ---------------------------------------------------------
eski2 = '''        else:
            karar = "IZLE"

        return {
'''

yeni2 = '''        else:
            karar = "IZLE"

        # Anlamli haber varsa AI nihai karara kontrollu mudahale eder.
        if haber_ai_aktif:
            if haber_ai_karar == "GUCLU_AL_ADAYI":
                karar = "AL"

            elif haber_ai_karar == "AL":
                # Cok guclu SAT teknik sinyali varsa tek haberle ezme.
                if sat_puani < 75:
                    karar = "AL"

            elif haber_ai_karar == "SAT":
                karar = "SAT"

            elif haber_ai_karar == "RISKLI_IZLE":
                if karar == "AL":
                    karar = "IZLE"

        return {
'''

if eski2 not in s:
    raise SystemExit("AI KARAR BAGLAMA NOKTASI BULUNAMADI")

s = s.replace(eski2, yeni2, 1)


# ---------------------------------------------------------
# RETURN ALANLARI
# ---------------------------------------------------------
eski3 = '''            "karar_nedenleri": karar_nedenleri,

            "puan": puan,
'''

yeni3 = '''            "karar_nedenleri": karar_nedenleri,

            # HABER / KAP AI
            "haber_ai_aktif": haber_ai_aktif,
            "haber_puani": round(haber_ai_puani, 2),
            "haber_guven": round(haber_ai_guven, 1),
            "haber_sinifi": haber_ai_sinifi,
            "haber_fiyat_teyidi": round(haber_fiyat_teyidi, 2),
            "haber_ai_karar": haber_ai_karar,
            "nihai_ai_puan": round(haber_nihai_ai_puan, 1),
            "haber_seviye_etkisi": round(haber_seviye_etkisi, 3),

            "puan": puan,
'''

if eski3 not in s:
    raise SystemExit("RETURN HABER AI NOKTASI BULUNAMADI")

s = s.replace(eski3, yeni3, 1)

p.write_text(s, encoding="utf-8")

print("HISSE DETAY HABER AI AL-SAT-STOP BAGLANTISI TAMAM")
