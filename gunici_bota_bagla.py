from pathlib import Path

p = Path("bist_bot.py")
s = p.read_text(encoding="utf-8")

old = '''    return top10, sonuclar, toplam


def gun_ici_top10_mesaji():'''

new = '''    # Gun Ici TOP 10 sonucunu web icin kaydet
    try:
        import json
        import os

        web_dosya = os.path.join(
            os.path.dirname(__file__),
            "webapp",
            "data",
            "gun_ici_top10.json"
        )

        os.makedirs(
            os.path.dirname(web_dosya),
            exist_ok=True
        )

        web_veri = {
            "guncelleme": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "toplam": toplam,
            "teknik_aday": len(sonuclar),
            "top10": top10
        }

        with open(web_dosya, "w", encoding="utf-8") as f:
            json.dump(
                web_veri,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )

        print(
            f"GUN ICI WEB VERISI KAYDEDILDI: {len(top10)} hisse"
        )

    except Exception as e:
        print("GUN ICI WEB KAYIT HATASI:", e)

    return top10, sonuclar, toplam


def gun_ici_top10_mesaji():'''

if old not in s:
    raise SystemExit(
        "HATA: Eklenecek yer bulunamadi. bist_bot.py degistirilmedi."
    )

s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")

print("BIST_BOT GUN ICI WEB BAGLANTISI EKLENDI")