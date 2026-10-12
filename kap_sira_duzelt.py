from pathlib import Path
import re

p = Path("kap_canli.py")
s = p.read_text(encoding="utf-8")

# Eski main calistirma blogunu bul ve kaldir
s = re.sub(
    r'\nif __name__ == ["\']__main__["\']:\s*\n\s+kap_kontrol\(\)\s*',
    '\n',
    s
)

# Main blogunu en sona tasi
s = s.rstrip() + '''

if __name__ == "__main__":
    kap_kontrol()
'''

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP FONKSIYON SIRASI DUZELTILDI")
