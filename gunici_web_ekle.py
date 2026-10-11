import json
import os

DATA_FILE = os.path.join(
    "webapp",
    "data",
    "bist_data.json"
)

def gun_ici_web_guncelle():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            veri = json.load(f)

        hisseler = veri.get("hisseler", [])

        gunici = [
            h for h in hisseler
            if float(h.get("gun_ici_puan", 0) or 0) > 0
        ]

        gunici.sort(
            key=lambda x: (
                float(x.get("gun_ici_puan", 0) or 0),
                float(x.get("hacim3_orani", 0) or 0),
                float(x.get("momentum15", 0) or 0)
            ),
            reverse=True
        )

        veri["gun_ici_top10"] = gunici[:10]

        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                veri,
                f,
                ensure_ascii=False,
                indent=2,
                default=str
            )

        print(
            "GUN ICI WEB TOP10 KAYDEDILDI:",
            len(veri["gun_ici_top10"])
        )

    except Exception as e:
        print("GUN ICI WEB TOP10 HATASI:", e)


if __name__ == "__main__":
    gun_ici_web_guncelle()