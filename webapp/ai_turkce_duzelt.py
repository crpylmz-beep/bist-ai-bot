from pathlib import Path

p = Path("index.html")
s = p.read_text(encoding="utf-8")

degisimler = {
    "AI ??renme Durumu": "AI Öğrenme Durumu",
    "VER? TOPLANIYOR": "VERİ TOPLANIYOR",
    "Ger?ek tamamlanm?? sinyal": "Gerçek tamamlanmış sinyal",
    "Ger?ek E?itim Sonucu": "Gerçek Eğitim Sonucu",
    "Kalan Minimum ?rnek": "Kalan Minimum Örnek",
    "Ba?ar? Oran?": "Başarı Oranı",
    "AI A??rl?klar?": "AI Ağırlıkları",
    "G?n ??i Veri Havuzu": "Gün İçi Veri Havuzu",
    "?ZLE": "İZLE",
    "??renilen G?stergeler": "Öğrenilen Göstergeler",
    "Hacimli K?r?l?m": "Hacimli Kırılım",
    "En az 30 ger?ek tamamlanm?? sinyal olu?madan ??renilmi? a??rl?klar teknik karar motoruna uygulanmaz.":
        "En az 30 gerçek tamamlanmış sinyal oluşmadan öğrenilmiş ağırlıklar teknik karar motoruna uygulanmaz.",
}

for eski, yeni in degisimler.items():
    s = s.replace(eski, yeni)

p.write_text(
    s,
    encoding="utf-8"
)

print("AI OGRENME TURKCE KARAKTERLER DUZELTILDI")
