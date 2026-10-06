from pathlib import Path
import shutil

p = Path("bist_bot.py")

yedek = Path("bist_bot_yarin_haber_ai_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

s = p.read_text(encoding="utf-8")

# =========================================================
# 1) YARIN POTANSIYEL HESABINDA HABER AI SEVIYELERI
# =========================================================

eski = '''        a["nihai_ai_puan"] = birlesik.get(
            "nihai_puan",
            teknik_puan
        )

        return max(
'''

yeni = '''        a["nihai_ai_puan"] = birlesik.get(
            "nihai_puan",
            teknik_puan
        )

        # =================================================
        # MADDE 44-47 - YARIN TOP10 DINAMIK HABER AI
        # =================================================
        a["yarin_haber_ai_aktif"] = False
        a["yarin_ai_karar"] = "IZLE"
        a["yarin_haber_fiyat_teyidi"] = 0.0
        a["yarin_haber_seviye_etkisi"] = 0.0

        # Varsayilan teknik seviyeler korunur.
        a["ai_yarin_alim_alt"] = guvenli_float(
            a.get("yarin_alim_alt")
        )
        a["ai_yarin_alim_ust"] = guvenli_float(
            a.get("yarin_alim_ust")
        )
        a["ai_yarin_hedef"] = guvenli_float(
            a.get("yarin_kar_al")
        )
        a["ai_yarin_stop"] = guvenli_float(
            a.get("yarin_stop")
        )

        try:
            haber_puani_ai = guvenli_float(
                a.get("haber_puani")
            )
            haber_guven_ai = guvenli_float(
                a.get("haber_guven")
            )

            haber_ai_aktif = (
                abs(haber_puani_ai) >= 0.5
                and haber_guven_ai >= 25
            )

            a["yarin_haber_ai_aktif"] = haber_ai_aktif

            if haber_ai_aktif:

                vwap_ai_ustu = None

                vwap_durum_ai = str(
                    a.get("vwap20_durum", "")
                )

                if vwap_durum_ai == "USTUNDE":
                    vwap_ai_ustu = True
                elif vwap_durum_ai == "ALTINDA":
                    vwap_ai_ustu = False

                ai_sonuc = (
                    haber_etki_motoru.hisse_haber_ai_guncelle(
                        teknik_puan=teknik_puan,
                        fiyat=fiyat,
                        atr=max(
                            guvenli_float(a.get("atr14")),
                            fiyat * 0.003
                        ),
                        destek=guvenli_float(
                            a.get("destek")
                        ),
                        direnc=guvenli_float(
                            a.get("direnc")
                        ),
                        haber_puani=haber_puani_ai,
                        haber_guven=haber_guven_ai,
                        sektor_puani=0,
                        makro_puani=0,
                        fiyat_degisim_yuzde=degisim,
                        hacim_orani=hacim,
                        vwap_ustu=vwap_ai_ustu,
                        obv_pozitif=None,
                        piyasa_rejimi=0,
                        haber_dakika=0,
                        ogrenilmis_katsayi=1.0,
                    )
                )

                a["yarin_ai_karar"] = ai_sonuc.get(
                    "ai_karar",
                    "IZLE"
                )

                a["yarin_haber_fiyat_teyidi"] = (
                    guvenli_float(
                        ai_sonuc.get("fiyat_teyidi")
                    )
                )

                a["yarin_haber_seviye_etkisi"] = (
                    guvenli_float(
                        ai_sonuc.get(
                            "haber_seviye_etkisi"
                        )
                    )
                )

                a["nihai_ai_puan"] = guvenli_float(
                    ai_sonuc.get(
                        "nihai_ai_puan",
                        a["nihai_ai_puan"]
                    )
                )

                a["ai_yarin_alim_alt"] = guvenli_float(
                    ai_sonuc.get(
                        "alim_alt",
                        a["ai_yarin_alim_alt"]
                    )
                )

                a["ai_yarin_alim_ust"] = guvenli_float(
                    ai_sonuc.get(
                        "alim_ust",
                        a["ai_yarin_alim_ust"]
                    )
                )

                a["ai_yarin_hedef"] = guvenli_float(
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

        except Exception:
            pass

        return max(
'''

if eski not in s:
    raise SystemExit(
        "YARIN HABER AI SEVIYE BAGLAMA NOKTASI BULUNAMADI"
    )

s = s.replace(eski, yeni, 1)


# =========================================================
# 2) EXCEPT DURUMUNDA DA AI SEVIYE ANAHTARLARI BULUNSUN
# =========================================================

eski2 = '''        a["nihai_ai_puan"] = teknik_puan
        return teknik_puan
'''

yeni2 = '''        a["nihai_ai_puan"] = teknik_puan
        a["yarin_haber_ai_aktif"] = False
        a["yarin_ai_karar"] = "IZLE"
        a["yarin_haber_fiyat_teyidi"] = 0.0
        a["yarin_haber_seviye_etkisi"] = 0.0
        a["ai_yarin_alim_alt"] = guvenli_float(
            a.get("yarin_alim_alt")
        )
        a["ai_yarin_alim_ust"] = guvenli_float(
            a.get("yarin_alim_ust")
        )
        a["ai_yarin_hedef"] = guvenli_float(
            a.get("yarin_kar_al")
        )
        a["ai_yarin_stop"] = guvenli_float(
            a.get("yarin_stop")
        )
        return teknik_puan
'''

if eski2 not in s:
    raise SystemExit(
        "YARIN HABER AI FALLBACK NOKTASI BULUNAMADI"
    )

s = s.replace(eski2, yeni2, 1)


# =========================================================
# 3) YARIN TOP10 EKRANINA AI KARAR / ALIM / HEDEF / STOP
# =========================================================

eski3 = '''            f"   🤖 Nihai AI: "
            f"{guvenli_float(a.get('nihai_ai_puan', skor)):.0f}/100 | "
            f"{a.get('haber_sinifi', 'NOTR')} | "
            f"Güven %{guvenli_float(a.get('haber_guven', 0)):.0f}\\n"
            f"   💰 {guvenli_float(a.get('fiyat')):.2f} TL "
'''

yeni3 = '''            f"   🤖 Nihai AI: "
            f"{guvenli_float(a.get('nihai_ai_puan', skor)):.0f}/100 | "
            f"{a.get('haber_sinifi', 'NOTR')} | "
            f"Güven %{guvenli_float(a.get('haber_guven', 0)):.0f}\\n"
            f"   🧭 AI Kararı: "
            f"{a.get('yarin_ai_karar', 'IZLE')} | "
            f"Fiyat Teyidi "
            f"{guvenli_float(a.get('yarin_haber_fiyat_teyidi', 0)):+.1f}\\n"
            f"   🎯 Alım Bölgesi: "
            f"{guvenli_float(a.get('ai_yarin_alim_alt', a.get('yarin_alim_alt'))):.2f} - "
            f"{guvenli_float(a.get('ai_yarin_alim_ust', a.get('yarin_alim_ust'))):.2f} TL\\n"
            f"   💵 AI Hedef: "
            f"{guvenli_float(a.get('ai_yarin_hedef', a.get('yarin_kar_al'))):.2f} TL | "
            f"🛑 AI Stop: "
            f"{guvenli_float(a.get('ai_yarin_stop', a.get('yarin_stop'))):.2f} TL\\n"
            f"   💰 {guvenli_float(a.get('fiyat')):.2f} TL "
'''

if eski3 not in s:
    raise SystemExit(
        "YARIN TOP10 AI EKRAN NOKTASI BULUNAMADI"
    )

s = s.replace(eski3, yeni3, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("YARIN TOP10 HABER AI ALIM-HEDEF-STOP BAGLANTISI TAMAM")
