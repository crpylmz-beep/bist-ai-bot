p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

eski = '''TAHMIN_GECMISI_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "tahmin_gecmisi.json"
)
'''

yeni = '''TAHMIN_GECMISI_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "tahmin_gecmisi.json"
)

YARIN_TOP10_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "yarin_top10.json"
)
'''

if eski not in s:
    raise SystemExit("HEDEF BLOK BULUNAMADI")

s = s.replace(eski, yeni, 1)

with open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(s)

print("YARIN TOP10 DOSYA YOLU EKLENDI")