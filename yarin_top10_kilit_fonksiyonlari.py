p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

hedef = "\ndef tahminleri_kaydet(sonuclar, toplam_hisse):"

if hedef not in s:
    raise SystemExit("EKLENECEK YER BULUNAMADI")

kod = r'''

def yarin_top10_kilitli_oku():
    try:
        if not os.path.exists(YARIN_TOP10_FILE):
            return None

        with open(YARIN_TOP10_FILE, "r", encoding="utf-8") as f:
            veri = json.load(f)

        if not isinstance(veri, dict):
            return None

        return veri

    except Exception as e:
        print("YARIN TOP10 OKUMA HATASI:", e)
        return None


def yarin_top10_kilitli_kaydet(sonuclar, toplam_hisse):
    try:
        top10 = yarin_top10_listesi(sonuclar)

        kayitlar = []

        for sira, (skor, a) in enumerate(top10, 1):
            hisse = dict(a)

            hisse["yarin_top10_sira"] = sira
            hisse["yarin_top10_puani"] = skor

            # Kilitlenen ilk listede henuz ilk hacimli kirilim
            # saati bilinmiyor. Gun ici takip sistemi daha sonra
            # bu alani ilk gerceklesme aninda dolduracak.
            hisse["ilk_hacimli_kirilim_saati"] = None

            kayitlar.append(hisse)

        simdi = datetime.now()

        veri = {
            "olusturma_zamani": simdi.strftime("%Y-%m-%d %H:%M:%S"),
            "analiz_tarihi": simdi.strftime("%Y-%m-%d"),
            "kilitli": True,
            "toplam_hisse": toplam_hisse,
            "teknik_aday": len([
                a for a in sonuclar
                if yarin_potansiyel_hesapla(a) >= 55
            ]),
            "top10": kayitlar
        }

        os.makedirs(
            os.path.dirname(YARIN_TOP10_FILE),
            exist_ok=True
        )

        with open(
            YARIN_TOP10_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                veri,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )

        print(
            f"YARIN TOP10 KILITLENDI: "
            f"{len(kayitlar)} hisse"
        )

        return veri

    except Exception as e:
        print("YARIN TOP10 KILITLEME HATASI:", e)
        return None
'''

s = s.replace(
    hedef,
    kod + hedef,
    1
)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 KILIT FONKSIYONLARI EKLENDI")