from pathlib import Path

p = Path("index.html")
s = p.read_text(encoding="utf-8")

s = s.replace(
    "En az 30 ger?ek tamamlanm?? sinyal olu?madan ??renilmi? a??rl?klar teknik karar motoruna uygulanmaz.",
    "En az 30 gerçek tamamlanmış sinyal oluşmadan öğrenilmiş ağırlıklar teknik karar motoruna uygulanmaz."
)

p.write_text(
    s,
    encoding="utf-8"
)

print("SON TURKCE METIN DUZELTILDI")
