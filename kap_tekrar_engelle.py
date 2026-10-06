from pathlib import Path

p = Path("kap_canli.py")
s = p.read_text(encoding="utf-8")

ek = r'''

import json
import hashlib
from pathlib import Path as _Path

DURUM_DOSYA = _Path("kap_son_gorulen.json")


def _durum_oku():
    try:
        if DURUM_DOSYA.exists():
            return set(
                json.loads(
                    DURUM_DOSYA.read_text(
                        encoding="utf-8"
                    )
                )
            )
    except Exception:
        pass

    return set()


def _durum_yaz(ids):
    DURUM_DOSYA.write_text(
        json.dumps(
            sorted(list(ids)),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def _kayit_id(kayit):
    raw = (
        str(kayit.get("sembol", ""))
        + "|"
        + str(kayit.get("ham_metin", ""))
    ).encode(
        "utf-8",
        errors="ignore"
    )

    return hashlib.sha1(raw).hexdigest()


def sadece_yeni_bildirimler(bildirimler):
    gorulen = _durum_oku()

    yeniler = []

    for kayit in bildirimler:
        kid = _kayit_id(kayit)

        if kid in gorulen:
            continue

        yeniler.append(kayit)
        gorulen.add(kid)

    _durum_yaz(gorulen)

    return yeniler
'''

if "def sadece_yeni_bildirimler(" not in s:
    s += ek

eski = '''    bildirimler = kap_bildirimleri_ayir(
        html
    )

    print(
        f"KAP BILDIRIM SAYISI: "
        f"{len(bildirimler)}"
    )

    for kayit in bildirimler[:20]:
'''

yeni = '''    bildirimler = kap_bildirimleri_ayir(
        html
    )

    yeniler = sadece_yeni_bildirimler(
        bildirimler
    )

    print(
        f"KAP TOPLAM: {len(bildirimler)} | "
        f"YENI: {len(yeniler)}"
    )

    for kayit in yeniler[:20]:
'''

if eski in s:
    s = s.replace(
        eski,
        yeni,
        1
    )

p.write_text(
    s,
    encoding="utf-8"
)

print("KAP TEKRAR ENGELLEME EKLENDI")
