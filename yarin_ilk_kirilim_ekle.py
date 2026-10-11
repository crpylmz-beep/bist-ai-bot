p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

hedef = "\ndef gun_ici_analiz_hesapla(sembol, veri=None):"

if hedef not in s:
    raise SystemExit("GUN ICI ANALIZ FONKSIYONU BULUNAMADI")

yeni_fonksiyon = r'''

def ilk_hacimli_kirilim_bul(veri, kirilim_seviyesi):
    """
    5 dakikalik mumlari sirayla kontrol eder.
    Ilk kez kirilim seviyesinin uzerinde kapanan ve
    hacmi onceki 20 adet 5 dk mum ortalamasinin
    en az %130'u olan mumun saatini dondurur.
    """

    try:
        if veri is None or veri.empty:
            return None, "BEKLENIYOR"

        seviye = guvenli_float(kirilim_seviyesi)

        if seviye <= 0:
            return None, "BEKLENIYOR"

        veri = veri.dropna(
            subset=["Open", "High", "Low", "Close", "Volume"]
        ).copy()

        if veri.empty:
            return None, "BEKLENIYOR"

        # Yalnizca son islem gununun mumlari.
        son_tarih = veri.index[-1].date()

        bugun = veri[
            veri.index.date == son_tarih
        ].copy()

        if len(bugun) < 2:
            return None, "BEKLENIYOR"

        fiyat_kirdi = False

        for i in range(1, len(bugun)):

            onceki_kapanis = guvenli_float(
                bugun["Close"].iloc[i - 1]
            )

            kapanis = guvenli_float(
                bugun["Close"].iloc[i]
            )

            # Kapanis bazli gercek yukari gecis.
            yeni_kirilim = (
                onceki_kapanis <= seviye
                and kapanis > seviye
            )

            if not yeni_kirilim:
                continue

            fiyat_kirdi = True

            # Mumun kendisini ortalamaya katmiyoruz.
            onceki_hacimler = bugun["Volume"].iloc[
                max(0, i - 20):i
            ].astype(float)

            # Saglikli hacim teyidi icin en az 3 onceki mum.
            if len(onceki_hacimler) < 3:
                continue

            ort_hacim = guvenli_float(
                onceki_hacimler.mean()
            )

            mum_hacmi = guvenli_float(
                bugun["Volume"].iloc[i]
            )

            if ort_hacim <= 0:
                continue

            hacim_orani = (
                mum_hacmi / ort_hacim
            ) * 100

            if hacim_orani >= 130:

                saat = bugun.index[i].strftime(
                    "%H:%M"
                )

                return saat, "GERCEKLESTI"

        if fiyat_kirdi:
            return None, "HACIM_ZAYIF"

        return None, "BEKLENIYOR"

    except Exception as e:
        print(
            "ILK HACIMLI KIRILIM HATASI:",
            e
        )
        return None, "BEKLENIYOR"


'''

s = s.replace(
    hedef,
    yeni_fonksiyon + hedef,
    1
)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("ILK HACIMLI KIRILIM FONKSIYONU EKLENDI")