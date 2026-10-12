
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import bist_bot


# =========================================================
# BIST ASISTANI - CANLI ARKA PLAN MOTORU
# MADDE 48
# =========================================================

DURUM_DOSYA = Path("webapp/data/canli_motor_durum.json")

# Veri kaynagini gereksiz yere bogmamak icin sinirli paralellik.
MAX_WORKERS = 6

# Her kac hisse sonucunda web JSON yeniden yazilsin.
ARA_KAYIT_ADEDI = 25

# Gun ici TOP10 yeniden hesaplama araligi.
GUN_ICI_TOP10_SANIYE = 300

# Tarama bittikten sonra yeni turun baslama araligi.
# Tarama zaten uzun surerse hemen yeni tur baslar.
TUR_ARASI_SANIYE = 30


def simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def durum_yaz(**alanlar):
    try:
        DURUM_DOSYA.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        mevcut = {}

        if DURUM_DOSYA.exists():
            try:
                mevcut = json.loads(
                    DURUM_DOSYA.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception:
                mevcut = {}

        mevcut.update(alanlar)
        mevcut["son_durum_guncelleme"] = simdi()

        DURUM_DOSYA.write_text(
            json.dumps(
                mevcut,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

    except Exception:
        pass


def tek_hisse_guncelle(sembol):
    try:
        sonuc = bist_bot.hisse_analiz_hesapla(
            sembol,
            period="6mo"
        )

        if not sonuc:
            return sembol, None

        return sembol, sonuc

    except Exception:
        return sembol, None


def tam_hisse_turu():
    """
    Tum BIST hisselerini paralel ama kontrollu sekilde
    yeniden analiz eder.

    Her ARA_KAYIT_ADEDI hissede Hisse Ara JSON'u
    yeniden yazilir. Boylece tum turun bitmesi
    beklenmeden uygulama guncellenmeye baslar.
    """

    semboller = bist_bot.bist_hisseleri_getir()

    if not semboller:
        print("BIST sembol listesi alinamadi.")
        return {}

    semboller = [
        str(x).strip().upper()
        for x in semboller
        if str(x).strip()
    ]

    toplam = len(semboller)

    print()
    print(
        f"CANLI HISSE TURU BASLADI | "
        f"{toplam} hisse | {simdi()}"
    )

    durum_yaz(
        motor="AKTIF",
        durum="HISSE_TARAMASI",
        toplam_hisse=toplam,
        taranan_hisse=0,
        tur_baslangic=simdi()
    )

    cache = {}
    tamamlanan = 0
    basarili = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        gorevler = {
            executor.submit(
                tek_hisse_guncelle,
                sembol
            ): sembol
            for sembol in semboller
        }

        for future in as_completed(gorevler):

            sembol = gorevler[future]

            try:
                _, sonuc = future.result()
            except Exception:
                sonuc = None

            tamamlanan += 1

            if sonuc:
                cache[sembol] = sonuc
                basarili += 1

            # Tum turun bitmesini beklemeden web verisini yenile.
            if (
                tamamlanan % ARA_KAYIT_ADEDI == 0
                or tamamlanan == toplam
            ):
                try:
                    bist_bot.web_verisi_kaydet(
                        list(cache.values()),
                        semboller
                    )

                    durum_yaz(
                        taranan_hisse=tamamlanan,
                        basarili_hisse=basarili,
                        son_web_yazma=simdi()
                    )

                    print(
                        f"CANLI: {tamamlanan}/{toplam} | "
                        f"Hazir: {basarili}"
                    )

                except Exception as e:
                    print(
                        "WEB VERI YAZMA HATASI:",
                        e
                    )

    durum_yaz(
        durum="TUR_TAMAMLANDI",
        taranan_hisse=toplam,
        basarili_hisse=basarili,
        son_tam_tur=simdi()
    )

    print(
        f"CANLI HISSE TURU TAMAMLANDI | "
        f"{basarili}/{toplam} | {simdi()}"
    )

    return cache


def gun_ici_top10_guncelle():
    """
    Gun Ici TOP10 motorunu kullanici ekran acmadan
    arka planda tetikler.
    """

    try:
        print(
            f"GUN ICI TOP10 ARKA PLAN HESABI | {simdi()}"
        )

        top10, sonuclar, toplam = (
            bist_bot.gun_ici_top10_tara()
        )

        durum_yaz(
            son_gun_ici_top10=simdi(),
            gun_ici_top10_adet=len(top10 or []),
            gun_ici_aday_adet=len(sonuclar or []),
            gun_ici_taranan=toplam or 0
        )

        print(
            f"GUN ICI TOP10 TAMAM | "
            f"TOP10: {len(top10 or [])} | "
            f"Aday: {len(sonuclar or [])}"
        )

    except Exception as e:
        print(
            "GUN ICI TOP10 ARKA PLAN HATASI:",
            e
        )


def motoru_calistir():

    print("=" * 58)
    print("BIST ASISTANI CANLI ARKA PLAN MOTORU")
    print("Tum hisseler + Hisse Ara + Gun Ici TOP10")
    print("=" * 58)

    durum_yaz(
        motor="AKTIF",
        baslangic=simdi()
    )

    son_gun_ici_top10 = 0

    while True:

        try:
            # Tum hisseleri tazele.
            tam_hisse_turu()

            # Gun Ici TOP10 5 dakikadan eskiyse yenile.
            simdi_ts = time.time()

            if (
                simdi_ts - son_gun_ici_top10
                >= GUN_ICI_TOP10_SANIYE
            ):
                gun_ici_top10_guncelle()
                son_gun_ici_top10 = time.time()

            durum_yaz(
                motor="AKTIF",
                durum="YENI_TUR_BEKLIYOR"
            )

            time.sleep(TUR_ARASI_SANIYE)

        except KeyboardInterrupt:

            durum_yaz(
                motor="DURDU",
                durum="KULLANICI_DURDURDU"
            )

            print()
            print("CANLI MOTOR DURDURULDU.")
            break

        except Exception as e:

            durum_yaz(
                motor="HATA",
                hata=str(e)
            )

            print(
                "CANLI MOTOR HATASI:",
                e
            )

            traceback.print_exc()

            # Gecici hata tum sistemi durdurmasin.
            time.sleep(30)


if __name__ == "__main__":
    motoru_calistir()
