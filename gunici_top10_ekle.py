from pathlib import Path

DOSYA = Path("bist_bot.py")

kod = DOSYA.read_text(encoding="utf-8")

ISARET = "# =========================================================\n# YARIN POTANSİYEL HESAPLAMA"

if "def gun_ici_analiz_hesapla(" in kod:
    print("GUN ICI TOP 10 KODU ZATEN EKLENMIS")
    raise SystemExit

if ISARET not in kod:
    print("EKLEME NOKTASI BULUNAMADI")
    raise SystemExit(1)

YENI_KOD = r'''
# =========================================================
# GUN ICI TOP 10
# =========================================================

def gun_ici_analiz_hesapla(sembol):
    """
    5 dakikalik mumlarla gun ici guc analizi.
    Yarin TOP 10 algoritmasindan tamamen ayridir.
    """

    try:
        hisse = bp.Ticker(sembol)

        veri = hisse.history(
            period="5d",
            interval="5m"
        )

        if veri is None or veri.empty:
            return None

        if len(veri) < 30:
            return None

        veri = veri.dropna(
            subset=["Open", "High", "Low", "Close", "Volume"]
        )

        if len(veri) < 30:
            return None

        # Son mumun ait oldugu islem gunu.
        son_tarih = veri.index[-1].date()

        bugun = veri[
            veri.index.date == son_tarih
        ].copy()

        if bugun.empty or len(bugun) < 3:
            return None

        close = veri["Close"].astype(float)
        volume = veri["Volume"].astype(float)

        son = bugun.iloc[-1]

        fiyat = guvenli_float(
            son["Close"]
        )

        gun_acilis = guvenli_float(
            bugun.iloc[0]["Open"]
        )

        gun_yuksek = guvenli_float(
            bugun["High"].max()
        )

        gun_dusuk = guvenli_float(
            bugun["Low"].min()
        )

        if fiyat <= 0 or gun_acilis <= 0:
            return None

        # Gunluk degisim: gunun ilk 5 dk acilisina gore.
        acilisa_gore_degisim = (
            (fiyat - gun_acilis)
            / gun_acilis
        ) * 100

        # Gun ici dipten toparlanma.
        if gun_dusuk > 0:
            dipten_toparlanma = (
                (fiyat - gun_dusuk)
                / gun_dusuk
            ) * 100
        else:
            dipten_toparlanma = 0

        # Gun ici zirveye uzaklik.
        if gun_yuksek > 0:
            zirveye_uzaklik = (
                (gun_yuksek - fiyat)
                / gun_yuksek
            ) * 100
        else:
            zirveye_uzaklik = 0

        # -------------------------------------------------
        # RSI 14 - 5 DAKIKA
        # -------------------------------------------------

        delta = close.diff()

        kazanc = delta.clip(
            lower=0
        )

        kayip = -delta.clip(
            upper=0
        )

        ort_kazanc = kazanc.rolling(14).mean()
        ort_kayip = kayip.rolling(14).mean()

        son_kazanc = guvenli_float(
            ort_kazanc.iloc[-1]
        )

        son_kayip = guvenli_float(
            ort_kayip.iloc[-1]
        )

        if son_kayip == 0:
            rsi5 = 100 if son_kazanc > 0 else 50
        else:
            rs = son_kazanc / son_kayip
            rsi5 = 100 - (100 / (1 + rs))

        # -------------------------------------------------
        # MACD - 5 DAKIKA
        # -------------------------------------------------

        ema12 = close.ewm(
            span=12,
            adjust=False
        ).mean()

        ema26 = close.ewm(
            span=26,
            adjust=False
        ).mean()

        macd_seri = ema12 - ema26

        signal_seri = macd_seri.ewm(
            span=9,
            adjust=False
        ).mean()

        hist_seri = macd_seri - signal_seri

        macd5 = guvenli_float(
            macd_seri.iloc[-1]
        )

        signal5 = guvenli_float(
            signal_seri.iloc[-1]
        )

        hist5 = guvenli_float(
            hist_seri.iloc[-1]
        )

        hist_onceki = guvenli_float(
            hist_seri.iloc[-2]
        )

        # -------------------------------------------------
        # HACIM HIZLANMASI
        # -------------------------------------------------

        son_hacim = guvenli_float(
            volume.iloc[-1]
        )

        onceki_hacimler = volume.iloc[-21:-1]

        ort_hacim20_5dk = guvenli_float(
            onceki_hacimler.mean()
        )

        if ort_hacim20_5dk > 0:
            hacim_hizlanma = (
                son_hacim
                / ort_hacim20_5dk
            ) * 100
        else:
            hacim_hizlanma = 0

        # Son 3 mum hacmi / onceki 20 mum ortalamasi.
        son3_hacim = guvenli_float(
            volume.iloc[-3:].mean()
        )

        if ort_hacim20_5dk > 0:
            hacim3_orani = (
                son3_hacim
                / ort_hacim20_5dk
            ) * 100
        else:
            hacim3_orani = 0

        # -------------------------------------------------
        # KISA VADE MOMENTUM
        # -------------------------------------------------

        if len(close) >= 4:
            fiyat_15dk_once = guvenli_float(
                close.iloc[-4]
            )

            if fiyat_15dk_once > 0:
                momentum15 = (
                    (fiyat - fiyat_15dk_once)
                    / fiyat_15dk_once
                ) * 100
            else:
                momentum15 = 0
        else:
            momentum15 = 0

        if len(close) >= 7:
            fiyat_30dk_once = guvenli_float(
                close.iloc[-7]
            )

            if fiyat_30dk_once > 0:
                momentum30 = (
                    (fiyat - fiyat_30dk_once)
                    / fiyat_30dk_once
                ) * 100
            else:
                momentum30 = 0
        else:
            momentum30 = 0

        # -------------------------------------------------
        # YAKIN KIRILIM
        # Son tamamlanmis 12 mumun tepesini referans al.
        # Son mumu direncten cikar.
        # -------------------------------------------------

        onceki_mumlar = veri.iloc[-13:-1]

        if not onceki_mumlar.empty:
            yakin_direnc = guvenli_float(
                onceki_mumlar["High"].max()
            )
        else:
            yakin_direnc = gun_yuksek

        kirilim = (
            yakin_direnc > 0
            and fiyat > yakin_direnc
        )

        hacimli_kirilim = (
            kirilim
            and hacim3_orani >= 130
        )

        # -------------------------------------------------
        # PUANLAMA
        # -------------------------------------------------

        puan = 0
        nedenler = []

        # Sert risk filtresi:
        # cok sert eksi veya tavan benzeri hareketi kovalamiyoruz.
        if acilisa_gore_degisim <= -7:
            return None

        if acilisa_gore_degisim >= 9.5:
            return None

        # Acilisa gore guc.
        if 0.5 <= acilisa_gore_degisim <= 3:
            puan += 12
            nedenler.append("Acilisa gore guclu")

        elif 3 < acilisa_gore_degisim <= 5:
            puan += 9
            nedenler.append("Pozitif gun ici momentum")

        elif 5 < acilisa_gore_degisim < 8:
            puan += 4

        elif -1 <= acilisa_gore_degisim < 0.5:
            puan += 2

        # Dipten toparlanma.
        if 1 <= dipten_toparlanma <= 4:
            puan += 10
            nedenler.append("Dipten toparlanma")

        elif 4 < dipten_toparlanma <= 7:
            puan += 7

        elif dipten_toparlanma > 7:
            puan += 3

        # Zirveye yakinlik.
        if zirveye_uzaklik <= 0.5:
            puan += 10
            nedenler.append("Gun ici zirveye yakin")

        elif zirveye_uzaklik <= 1.5:
            puan += 7

        elif zirveye_uzaklik <= 3:
            puan += 3

        # RSI.
        if 50 <= rsi5 <= 68:
            puan += 12
            nedenler.append("5dk RSI guclu")

        elif 45 <= rsi5 < 50:
            puan += 6

        elif 68 < rsi5 < 75:
            puan += 4

        elif rsi5 >= 80:
            puan -= 8

        elif rsi5 < 30:
            puan -= 8

        # MACD.
        if macd5 > signal5:
            puan += 9
            nedenler.append("5dk MACD pozitif")

        if hist5 > 0:
            puan += 5

        if hist5 > hist_onceki:
            puan += 5
            nedenler.append("Momentum artiyor")

        # Hacim.
        if hacim3_orani >= 200:
            puan += 15
            nedenler.append("Cok guclu hacim")

        elif hacim3_orani >= 150:
            puan += 12
            nedenler.append("Guclu hacim")

        elif hacim3_orani >= 120:
            puan += 8

        elif hacim3_orani < 60:
            puan -= 5

        # Son 15 / 30 dakika momentum.
        if 0.2 <= momentum15 <= 1.5:
            puan += 6

        elif momentum15 > 1.5:
            puan += 3

        elif momentum15 <= -1:
            puan -= 5

        if 0.3 <= momentum30 <= 2.5:
            puan += 6

        elif momentum30 <= -1.5:
            puan -= 5

        # Kirilim.
        if hacimli_kirilim:
            puan += 15
            nedenler.append("Hacimli kirilim")

        elif kirilim:
            puan += 6
            nedenler.append("Direnc kirilimi")

        puan = max(
            0,
            min(100, puan)
        )

        return {
            "sembol": sembol,
            "fiyat": fiyat,
            "gun_ici_puan": puan,
            "acilisa_gore_degisim": acilisa_gore_degisim,
            "dipten_toparlanma": dipten_toparlanma,
            "zirveye_uzaklik": zirveye_uzaklik,
            "rsi5": rsi5,
            "macd5": macd5,
            "signal5": signal5,
            "hist5": hist5,
            "hist_onceki": hist_onceki,
            "hacim_hizlanma": hacim_hizlanma,
            "hacim3_orani": hacim3_orani,
            "momentum15": momentum15,
            "momentum30": momentum30,
            "gun_yuksek": gun_yuksek,
            "gun_dusuk": gun_dusuk,
            "yakin_direnc": yakin_direnc,
            "kirilim": bool(kirilim),
            "hacimli_kirilim": bool(hacimli_kirilim),
            "nedenler": nedenler,
            "veri_tarihi": str(veri.index[-1])
        }

    except Exception:
        return None


def gun_ici_top10_tara():
    """
    Tum BIST hisselerini 5 dakikalik verilerle tarar.
    Yalnizca Gun Ici TOP 10 icindir.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    semboller = bist_hisseleri_getir()

    toplam = len(semboller)

    sonuclar = []

    tamamlanan = 0

    max_workers = 8

    print(
        f"GUN ICI TARAMA BASLADI: {toplam} hisse"
    )

    with ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:

        futures = {
            executor.submit(
                gun_ici_analiz_hesapla,
                sembol
            ): sembol
            for sembol in semboller
        }

        for future in as_completed(futures):

            tamamlanan += 1

            try:
                analiz = future.result()

                if analiz:
                    sonuclar.append(
                        analiz
                    )

            except Exception:
                pass

            if tamamlanan % 25 == 0:
                print(
                    f"GUN ICI: {tamamlanan}/{toplam}"
                )

    # Once puan, sonra hacim ve momentum.
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

    return top10, sonuclar, toplam


def gun_ici_top10_mesaji():
    """
    Terminal / Telegram icin okunabilir Gun Ici TOP 10.
    """

    top10, sonuclar, toplam = gun_ici_top10_tara()

    if not top10:
        return (
            "⚡ GÜN İÇİ TOP 10\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🔎 Taranan hisse: {toplam}\n"
            "Uygun gün içi aday bulunamadı."
        )

    satirlar = [
        "⚡ GÜN İÇİ TOP 10",
        "━━━━━━━━━━━━━━",
        "",
        f"🔎 Taranan hisse: {toplam}",
        f"📊 Teknik aday: {len(sonuclar)}",
        ""
    ]

    for sira, a in enumerate(
        top10,
        start=1
    ):

        satirlar.extend([
            (
                f"{sira}. {a['sembol']} — "
                f"{a['gun_ici_puan']:.0f}/100"
            ),
            (
                f"   💰 {a['fiyat']:.2f} TL | "
                f"Açılışa göre "
                f"{a['acilisa_gore_degisim']:+.2f}%"
            ),
            (
                f"   RSI(5dk) {a['rsi5']:.1f} | "
                f"Hacim %{a['hacim3_orani']:.0f}"
            ),
            (
                f"   15dk {a['momentum15']:+.2f}% | "
                f"30dk {a['momentum30']:+.2f}%"
            ),
            (
                "   🚀 Hacimli kırılım"
                if a.get("hacimli_kirilim")
                else (
                    "   🟡 Direnç kırılımı"
                    if a.get("kirilim")
                    else "   ⚪ Kırılım bekleniyor"
                )
            ),
            ""
        ])

    return "\n".join(satirlar)


'''

kod = kod.replace(
    ISARET,
    YENI_KOD + "\n\n" + ISARET,
    1
)

DOSYA.write_text(
    kod,
    encoding="utf-8"
)

print("GUN ICI TOP 10 KODU EKLENDI")