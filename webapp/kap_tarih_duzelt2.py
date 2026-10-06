from pathlib import Path

p = Path("index.html")
s = p.read_text(encoding="utf-8")

eski = '${a.tarih || ""}'

yeni = '''${
    a.tarih
    ? (() => {
        const [tarih, saat = ""] = String(a.tarih).split(" ");
        const [yil, ay, gun] = tarih.split("-");
        return `${gun}/${ay}/${yil} ${saat}`;
      })()
    : ""
}'''

if eski not in s:
    raise SystemExit("TARIH ALANI BULUNAMADI")

s = s.replace(eski, yeni, 1)

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP TARIH FORMATI GG/AA/YYYY OLDU")
