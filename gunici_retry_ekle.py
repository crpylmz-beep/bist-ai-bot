from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

bas = s.index("def gun_ici_top10_tara():")
son = s.index("def gun_ici_top10_mesaji()", bas)

eski = s[bas:son]

yeni = r'''def gun_ici_top10_tara():
    """
    Tum BIST hisselerini 5 dakikalik verilerle tarar.
    Ilk tur hizli paralel tarama yapar.
    Veri gelmeyen hisseleri daha dusuk eszamanlilikla tekrar dener.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    semboller = bist_hisseleri_getir()
    toplam = len(semboller)

    sonuc_map = {}

    def paralel_tur(sembol_listesi, worker, tur_adi):
        bulunan = {}
        tamamlanan = 0

        if not sembol_listesi:
            return bulunan

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

                    if analiz:
                        bulunan[sembol] = analiz

                except Exception:
                    pass

                if tamamlanan % 25 == 0:
                    print(
                        f"{tur_adi}: "
                        f"{tamamlanan}/{len(sembol_listesi)}"
                    )

        return bulunan

    print(
        f"GUN ICI TARAMA BASLADI: {toplam} hisse"
    )

    # 1. TUR:
    # Hizli ana tarama.
    ilk_tur = paralel_tur(
        semboller,
        12,
        "1. TUR"
    )

    sonuc_map.update(ilk_tur)

    eksikler = [
        sembol
        for sembol in semboller
        if sembol not in sonuc_map
    ]

    print(
        f"1. TUR BASARILI: {len(sonuc_map)} | "
        f"EKSIK: {len(eksikler)}"
    )

    # 2. TUR:
    # Veri kaynaginin rahatlamasi icin kisa bekleme,
    # sonra daha dusuk eszamanlilik.
    if eksikler:
        time.sleep(2)

        ikinci_tur = paralel_tur(
            eksikler,
            6,
            "2. TUR"
        )

        sonuc_map.update(ikinci_tur)

        eksikler = [
            sembol
            for sembol in semboller
            if sembol not in sonuc_map
        ]

        print(
            f"2. TUR SONRASI BASARILI: "
            f"{len(sonuc_map)} | "
            f"EKSIK: {len(eksikler)}"
        )

    # 3. TUR:
    # Hala gelmeyenleri daha temkinli yeniden dene.
    if eksikler:
        time.sleep(3)

        ucuncu_tur = paralel_tur(
            eksikler,
            3,
            "3. TUR"
        )

        sonuc_map.update(ucuncu_tur)

        eksikler = [
            sembol
            for sembol in semboller
            if sembol not in sonuc_map
        ]

        print(
            f"3. TUR SONRASI BASARILI: "
            f"{len(sonuc_map)} | "
            f"EKSIK: {len(eksikler)}"
        )

    sonuclar = list(
        sonuc_map.values()
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

    # Eksik sembolleri sonradan kontrol edebilmek icin
    # fonksiyonun davranisini bozmadan ek bilgi yazdiriyoruz.
    if eksikler:
        print(
            "UYARI - VERI ALINAMAYAN HISSE SAYISI:",
            len(eksikler)
        )
        print(
            "ILK 30 EKSIK:",
            ", ".join(eksikler[:30])
        )
    else:
        print(
            "GUN ICI TARAMA TAM KAPSAM: "
            f"{len(sonuclar)}/{toplam}"
        )

    return top10, sonuclar, toplam


'''

s = s[:bas] + yeni + s[son:]

p.write_text(
    s,
    encoding="utf-8"
)

print("GUN ICI RETRY SISTEMI EKLENDI")