from pathlib import Path

p = Path("kap_canli.py")
s = p.read_text(encoding="utf-8")

eski = 'KAP_URL = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc"'
yeni = 'KAP_URL = "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc?cat=6&cmp=Y&slf=ALL&srcbar=Y"'

if eski in s:
    s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP CANLI URL DUZELTILDI")
