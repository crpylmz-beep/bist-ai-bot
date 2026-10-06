from pathlib import Path
import re

p = Path("index.html")
s = p.read_text(encoding="utf-8")

duzeltmeler = {
    "PAS?F": "PASİF",
    "Pas?f": "Pasif",
    "pas?f": "pasif",

    "ger?ek": "gerçek",
    "Ger?ek": "Gerçek",

    "tamamlanm??": "tamamlanmış",
    "Tamamlanm??": "Tamamlanmış",

    "olu?madan": "oluşmadan",
    "Olu?madan": "Oluşmadan",

    "??renilmi?": "öğrenilmiş",
    "??renilen": "Öğrenilen",
    "??renme": "Öğrenme",

    "a??rl?klar": "ağırlıklar",
    "A??rl?klar": "Ağırlıklar",

    "G?n": "Gün",
    "g?n": "gün",

    "?ZLE": "İZLE",

    "G?stergeler": "Göstergeler",
    "g?stergeler": "göstergeler",

    "K?r?l?m": "Kırılım",
    "k?r?l?m": "kırılım",

    "Ba?ar?": "Başarı",
    "ba?ar?": "başarı",

    "Oran?": "Oranı",
    "oran?": "oranı",

    "?rnek": "Örnek",
    "?rnek": "örnek",
}

for eski, yeni in duzeltmeler.items():
    s = s.replace(eski, yeni)

s = re.sub(
    r"En az 30 .*?teknik karar motoruna uygulanmaz\.",
    "En az 30 gerçek tamamlanmış sinyal oluşmadan öğrenilmiş ağırlıklar teknik karar motoruna uygulanmaz.",
    s
)

p.write_text(s, encoding="utf-8")

print("AI OGRENME EKRANI TURKCE KARAKTERLER TAMAMEN DUZELTILDI")
