from pathlib import Path

p = Path("kap_canli.py")
s = p.read_text(encoding="utf-8")

if "def kap_surekli_izle(" not in s:
    ek = r'''

import time


def kap_surekli_izle(bekleme_saniye=60):
    print(
        f"KAP CANLI IZLEME BASLADI | "
        f"Kontrol araligi: {bekleme_saniye} sn"
    )

    while True:
        try:
            kap_kontrol()

        except KeyboardInterrupt:
            print("KAP IZLEME DURDURULDU")
            break

        except Exception as e:
            print(
                "KAP IZLEME HATASI:",
                e
            )

        time.sleep(
            bekleme_saniye
        )
'''
    s += ek

s = s.replace(
    '''if __name__ == "__main__":
    kap_kontrol()
''',
    '''if __name__ == "__main__":
    kap_surekli_izle(60)
'''
)

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP SUREKLI IZLEME MOTORU EKLENDI")
