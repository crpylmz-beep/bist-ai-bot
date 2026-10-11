from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

bas = s.index("def gun_ici_top10_tara():")
son = s.index("def gun_ici_top10_mesaji()", bas)

yeni = r'''def gun_ici_top10_tara():
    """
    Tum BIST sembollerini 5 dakikalik verilerle tarar.

    NORMAL:
        Analize ve TOP 10 siralamasina girer.

    FILTRE_DISI:
        Veri vardir fakat risk filtresine takilmistir.
        Tekrar denenmez.

    GECERSIZ_SEMBOL:
        Veri kaynaginda gecersiz semboldur.
        Tekrar denenmez.

    GECICI_HATA:
        Baglanti/veri hatasidir.
        Sonraki turda tekrar denenir.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    semboller = bist_hisseleri_getir()
    toplam = len(semboller)

    normal_map = {}
    filtre_disi_map = {}
    gecersiz_map = {}
    gecici_hata_map = {}

    def paralel_tur(sembol_listesi, worker, tur_adi):
        normal = {}
        filtre_disi = {}
        gecersiz = {}
        gecici = {}

        tamamlanan = 0

        if not sembol_listesi:
            return normal, filtre_disi, gecersiz, gecici

        print(
            f"{tur_adi}: {len(sembol_listesi)} hisse "
            f"({worker} worker)"
        )

        with ThreadPoolExecutor(
            max_workers=worker
        ) as executor:

            futures = {
                executor.submit(
                    gun_ici_analiz_hesapla,
                    sembol
                ): sembol
                for sembol in sembol_listesi
            }

            for future in as_completed(futures):
                sembol = futures[future]
                tamamlanan += 1

                try:
                    analiz = future.result()

                    if analiz is None:
                        gecici[sembol] = {
                            "_durum": "GECICI_HATA",
                            "sembol": sembol,
                            "_hata": "BOS_SONUC"
                        }

                    else:
                        durum = analiz.get("_durum", "NORMAL")

                        if durum == "FILTRE_DISI":
                            filtre_disi[sembol] = analiz

                        elif durum == "GECERSIZ_SEMBOL":
                            gecersiz[sembol] = analiz

                        elif durum == "GECICI_HATA":
                            gecici[sembol] = analiz

                        else:
                            normal[sembol] = analiz

                except Exception as e:
                    gecici[sembol] = {
                        "_durum": "GECICI_HATA",
                        "sembol": sembol,
                        "_hata": str(e)
                    }

                if tamamlanan % 25 == 0:
                    print(
                        f"{tur_adi}: "
                        f"{tamamlanan}/{len(sembol_listesi)}"
                    )

        return normal, filtre_disi, gecersiz, gecici

    def sonuclari_ekle(
        normal,
        filtre_disi,
        gecersiz,
        gecici
    ):
        normal_map.update(normal)
        filtre_disi_map.update(filtre_disi)
        gecersiz_map.update(gecersiz)

        gecici_hata_map.clear()
        gecici_hata_map.update(gecici)

    print(
        f"GUN ICI TARAMA BASLADI: {toplam} hisse"
    )

    # 1. TUR
    n, f, g, h = paralel_tur(
        semboller,
        12,
        "1. TUR"
    )

    sonuclari_ekle(n, f, g, h)

    print(
        "1. TUR SONUCU | "
        f"NORMAL: {len(normal_map)} | "
        f"FILTRE DISI: {len(filtre_disi_map)} | "
        f"GECERSIZ: {len(gecersiz_map)} | "
        f"TEKRAR: {len(gecici_hata_map)}"
    )

    # Sadece gecici hatalar tekrar denenir.
    if gecici_hata_map:
        time.sleep(2)

        tekrar = list(
            gecici_hata_map.keys()
        )

        n, f, g, h = paralel_tur(
            tekrar,
            6,
            "2. TUR"
        )

        normal_map.update(n)
        filtre_disi_map.update(f)
        gecersiz_map.update(g)

        gecici_hata_map.clear()
        gecici_hata_map.update(h)

        print(
            "2. TUR SONUCU | "
            f"NORMAL: {len(normal_map)} | "
            f"FILTRE DISI: {len(filtre_disi_map)} | "
            f"GECERSIZ: {len(gecersiz_map)} | "
            f"TEKRAR: {len(gecici_hata_map)}"
        )

    # Son bir temkinli deneme.
    if gecici_hata_map:
        time.sleep(3)

        tekrar = list(
            gecici_hata_map.keys()
        )

        n, f, g, h = paralel_tur(
            tekrar,
            3,
            "3. TUR"
        )

        normal_map.update(n)
        filtre_disi_map.update(f)
        gecersiz_map.update(g)

        gecici_hata_map.clear()
        gecici_hata_map.update(h)

        print(
            "3. TUR SONUCU | "
            f"NORMAL: {len(normal_map)} | "
            f"FILTRE DISI: {len(filtre_disi_map)} | "
            f"GECERSIZ: {len(gecersiz_map)} | "
            f"KALAN HATA: {len(gecici_hata_map)}"
        )

    sonuclar = list(
        normal_map.values()
    )

    sonuclar.sort(
        key=lambda a: (
            guvenli_float(
                a.get("gun_ici_puan")
            ),
            guvenli_float(
                a.get("hacim3_orani")
            ),
            guvenli_float(
                a.get("momentum15")
            )
        ),
        reverse=True
    )

    top10 = [
        a
        for a in sonuclar
        if guvenli_float(
            a.get("gun_ici_puan")
        ) >= 45
    ][:10]

    print(
        "GUN ICI OZET | "
        f"TOPLAM: {toplam} | "
        f"ANALIZ: {len(normal_map)} | "
        f"FILTRE DISI: {len(filtre_disi_map)} | "
        f"GECERSIZ: {len(gecersiz_map)} | "
        f"HATA: {len(gecici_hata_map)}"
    )

    if gecici_hata_map:
        print(
            "KALAN HATALAR:",
            ", ".join(
                list(gecici_hata_map.keys())[:30]
            )
        )

    return top10, sonuclar, toplam


'''

s = s[:bas] + yeni + s[son:]

p.write_text(
    s,
    encoding="utf-8"
)

print("GUN ICI RETRY DURUM SISTEMI DUZELTILDI")