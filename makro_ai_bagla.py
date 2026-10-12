from pathlib import Path
import shutil

# =========================================================
# 1) MAKRO AI: HISSE BAZLI CANLI ETKI DOSYASI
# =========================================================

p = Path("makro_ai.py")
s = p.read_text(encoding="utf-8")

yedek = Path("makro_ai_canli_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

if "CANLI_MAKRO_DOSYA" not in s:
    s = s.replace(
        '''MAKRO_GECMIS = Path(
    "webapp/data/makro_ai_gecmisi.json"
)
''',
        '''MAKRO_GECMIS = Path(
    "webapp/data/makro_ai_gecmisi.json"
)

CANLI_MAKRO_DOSYA = Path(
    "webapp/data/makro_canli_etki.json"
)
''',
        1
    )

if "def canli_makro_etki_yaz(" not in s:
    ek = r'''

def canli_makro_etki_yaz(analiz, hisseler):
    """
    Son makro olayinin hisse bazli etkisini kalici JSON'a yazar.
    Bist karar motorlari bu dosyayi anlik okur.
    """
    import time

    veri = {
        "guncelleme": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "kategori": analiz.get(
            "kategori",
            "GENEL"
        ),
        "baslik": analiz.get(
            "baslik",
            ""
        ),
        "genel_puan": analiz.get(
            "genel_puan",
            0
        ),
        "hisseler": {}
    }

    for sembol, bilgi in hisseler.items():
        veri["hisseler"][sembol] = {
            "makro_puani": float(
                bilgi.get(
                    "makro_puani",
                    0
                ) or 0
            ),
            "sektor": bilgi.get(
                "sektor",
                ""
            ),
            "sektor_puani": float(
                bilgi.get(
                    "makro_puani",
                    0
                ) or 0
            )
        }

    CANLI_MAKRO_DOSYA.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    CANLI_MAKRO_DOSYA.write_text(
        json.dumps(
            veri,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    return veri
'''
    # Fonksiyonu makro_haber_isle öncesine ekle
    idx = s.find("def makro_haber_isle(")
    if idx == -1:
        raise SystemExit("makro_haber_isle BULUNAMADI")

    s = s[:idx] + ek + "\n\n" + s[idx:]

# etkilenen hisseler bulunduktan sonra canlı etkiyi yaz
eski = '''    hisseler = etkilenen_hisseleri_bul(
        analiz
    )

    print(
'''

yeni = '''    hisseler = etkilenen_hisseleri_bul(
        analiz
    )

    # Hisse bazli makro/sektor etkisini karar motorlarina aktar.
    canli_makro_etki_yaz(
        analiz,
        hisseler
    )

    print(
'''

if "canli_makro_etki_yaz(\n        analiz,\n        hisseler" not in s:
    if eski not in s:
        raise SystemExit("MAKRO CANLI YAZMA NOKTASI BULUNAMADI")
    s = s.replace(eski, yeni, 1)

p.write_text(s, encoding="utf-8")


# =========================================================
# 2) BIST BOT: MAKRO ETKIYI CACHE ILE OKU
# =========================================================

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

yedek = Path("bist_bot_makro_ai_yedek.py")
if not yedek.exists():
    shutil.copy2(p, yedek)

if "def canli_makro_puani_getir(" not in s:

    yardimci = r'''

# =========================================================
# CANLI MAKRO / SEKTOR ETKI OKUYUCU
# =========================================================

_MAKRO_CACHE = {
    "mtime": None,
    "veri": {}
}


def canli_makro_puani_getir(sembol):
    """
    makro_canli_etki.json dosyasini mtime cache ile okur.
    Her hisse analizinde diski tekrar tekrar okumaz.
    """
    try:
        dosya = os.path.join(
            "webapp",
            "data",
            "makro_canli_etki.json"
        )

        if not os.path.exists(dosya):
            return {
                "makro_puani": 0.0,
                "sektor_puani": 0.0,
                "sektor": ""
            }

        mtime = os.path.getmtime(dosya)

        if _MAKRO_CACHE["mtime"] != mtime:
            with open(
                dosya,
                "r",
                encoding="utf-8"
            ) as f:
                _MAKRO_CACHE["veri"] = json.load(f)

            _MAKRO_CACHE["mtime"] = mtime

        hisseler = _MAKRO_CACHE[
            "veri"
        ].get(
            "hisseler",
            {}
        )

        bilgi = hisseler.get(
            str(sembol or "").strip().upper(),
            {}
        )

        return {
            "makro_puani": guvenli_float(
                bilgi.get("makro_puani")
            ),
            "sektor_puani": guvenli_float(
                bilgi.get("sektor_puani")
            ),
            "sektor": str(
                bilgi.get("sektor", "")
            )
        }

    except Exception:
        return {
            "makro_puani": 0.0,
            "sektor_puani": 0.0,
            "sektor": ""
        }

'''

    # hisse_analiz_hesapla fonksiyonundan hemen önce ekle
    idx = s.find("def hisse_analiz_hesapla(")
    if idx == -1:
        raise SystemExit("hisse_analiz_hesapla BULUNAMADI")

    s = s[:idx] + yardimci + "\n" + s[idx:]


# =========================================================
# 3) UC AI CAGRI NOKTASINDA SABIT 0'LARI CANLI PUANA CEVIR
# =========================================================

eski_cagri = '''                        sektor_puani=0,
                        makro_puani=0,
'''

yeni_cagri = '''                        sektor_puani=canli_makro_puani_getir(sembol).get(
                            "sektor_puani",
                            0
                        ),
                        makro_puani=canli_makro_puani_getir(sembol).get(
                            "makro_puani",
                            0
                        ),
'''

adet = s.count(eski_cagri)

if adet != 3:
    raise SystemExit(
        f"BEKLENEN 3 BAGLANTI NOKTASI, BULUNAN: {adet}"
    )

s = s.replace(
    eski_cagri,
    yeni_cagri
)


# =========================================================
# 4) RETURN ICINE MAKRO ALANLARINI DA EKLE
# =========================================================

# Hisse detay return
eski_return = '''            "haber_seviye_etkisi": round(haber_seviye_etkisi, 3),

            "puan": puan,
'''

yeni_return = '''            "haber_seviye_etkisi": round(haber_seviye_etkisi, 3),
            "makro_puani": canli_makro_puani_getir(sembol).get(
                "makro_puani",
                0
            ),
            "sektor_puani": canli_makro_puani_getir(sembol).get(
                "sektor_puani",
                0
            ),
            "makro_sektor": canli_makro_puani_getir(sembol).get(
                "sektor",
                ""
            ),

            "puan": puan,
'''

if eski_return not in s:
    raise SystemExit("HISSE DETAY MAKRO RETURN NOKTASI BULUNAMADI")

s = s.replace(eski_return, yeni_return, 1)


# Gün içi return
eski_gunici = '''            "gun_ici_haber_seviye_etkisi": round(
                gun_ici_haber_seviye_etkisi,
                3
            ),

            "gun_ici_karar": gun_ici_karar,
'''

yeni_gunici = '''            "gun_ici_haber_seviye_etkisi": round(
                gun_ici_haber_seviye_etkisi,
                3
            ),
            "makro_puani": canli_makro_puani_getir(sembol).get(
                "makro_puani",
                0
            ),
            "sektor_puani": canli_makro_puani_getir(sembol).get(
                "sektor_puani",
                0
            ),
            "makro_sektor": canli_makro_puani_getir(sembol).get(
                "sektor",
                ""
            ),

            "gun_ici_karar": gun_ici_karar,
'''

if eski_gunici not in s:
    raise SystemExit("GUN ICI MAKRO RETURN NOKTASI BULUNAMADI")

s = s.replace(eski_gunici, yeni_gunici, 1)

p.write_text(s, encoding="utf-8")

print("MAKRO AI -> HISSE / GUN ICI / YARIN MOTORLARI BAGLANDI")
