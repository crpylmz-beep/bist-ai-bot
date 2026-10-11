import json
import bist_bot

HISTORY_FILE = "webapp/data/tahmin_gecmisi.json"
BIST_FILE = "webapp/data/bist_data.json"

with open(HISTORY_FILE, "r", encoding="utf-8") as f:
    history = json.load(f)

with open(BIST_FILE, "r", encoding="utf-8") as f:
    stocks = json.load(f)["hisseler"]

yarin = {
    a.get("sembol"): {
        "sira": i + 1,
        "puan": skor,
    }
    for i, (skor, a) in enumerate(
        bist_bot.yarin_top10_listesi(stocks)
    )
}

tepki = {
    a.get("sembol"): {
        "sira": i + 1,
        "puan": bist_bot.tepki_puani(a),
    }
    for i, a in enumerate(
        bist_bot.tepki_top10(stocks)
    )
}

for kayit in history["tahminler"]:
    sembol = kayit.get("sembol")

    yarin_bilgi = yarin.get(sembol)
    tepki_bilgi = tepki.get(sembol)

    kayit["yarin_top10"] = bool(yarin_bilgi)
    kayit["yarin_top10_sira"] = (
        yarin_bilgi["sira"] if yarin_bilgi else None
    )
    kayit["yarin_top10_puani"] = (
        yarin_bilgi["puan"] if yarin_bilgi else None
    )

    kayit["tepki_top10"] = bool(tepki_bilgi)
    kayit["tepki_top10_sira"] = (
        tepki_bilgi["sira"] if tepki_bilgi else None
    )
    kayit["tepki_top10_puani"] = (
        tepki_bilgi["puan"] if tepki_bilgi else None
    )

with open(HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(
        history,
        f,
        ensure_ascii=False,
        indent=2,
    )

print("KAYIT:", len(history["tahminler"]))
print(
    "YARIN TOP10:",
    sum(
        1
        for x in history["tahminler"]
        if x.get("yarin_top10")
    ),
)
print(
    "TEPKI TOP10:",
    sum(
        1
        for x in history["tahminler"]
        if x.get("tepki_top10")
    ),
)