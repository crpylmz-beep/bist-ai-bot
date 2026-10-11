p = "bist_bot.py"

with open(p, "r", encoding="utf-8") as f:
    s = f.read()

if "YARIN_TOP10_FILE =" in s:
    print("YARIN_TOP10_FILE ZATEN VAR")
    raise SystemExit

hedef = '''GUN_ICI_GECERSIZ_FILE = os.path.join('''

eklenecek = '''YARIN_TOP10_FILE = os.path.join(
    os.path.dirname(__file__),
    "webapp",
    "data",
    "yarin_top10.json"
)

GUN_ICI_GECERSIZ_FILE = os.path.join('''

if hedef not in s:
    raise SystemExit("EKLENECEK YER BULUNAMADI")

s = s.replace(hedef, eklenecek, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(s)

print("YARIN TOP10 DOSYA YOLU EKLENDI")