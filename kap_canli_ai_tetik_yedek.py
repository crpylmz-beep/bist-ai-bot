
import re
import time
import json
import hashlib
import requests
import borsapy as bp
from pathlib import Path

from bs4 import BeautifulSoup
import haber_zeka


KAP_URL = (
    "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc"
    "?cat=6&cmp=Y&slf=ALL&srcbar=Y"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

DURUM_DOSYA = Path("kap_son_gorulen.json")


def bist_sembolleri_getir():
    try:
        df = bp.companies()

        semboller = set(
            str(x).upper().strip()
            for x in df["ticker"].dropna().tolist()
        )

        print(
            f"BIST SEMBOL LISTESI: {len(semboller)}"
        )

        return semboller

    except Exception as e:
        print(
            "BIST SEMBOL LISTESI HATASI:",
            e
        )
        return set()


BIST_SEMBOLLER = bist_sembolleri_getir()


def kap_sayfa_oku():
    r = requests.get(
        KAP_URL,
        headers=HEADERS,
        timeout=20
    )

    r.raise_for_status()
    return r.text


def sembol_bul(text):
    adaylar = re.findall(
        r"\b[A-Z0-9]{3,6}\b",
        text or ""
    )

    for x in adaylar:
        if x in BIST_SEMBOLLER:
            return x

    return None


def kap_bildirimleri_ayir(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    sonuc = []

    for tr in soup.find_all("tr"):

        hucreler = [
            td.get_text(
                " ",
                strip=True
            )
            for td in tr.find_all("td")
        ]

        if len(hucreler) < 4:
            continue

        tam = " | ".join(
            hucreler
        )

        sembol = sembol_bul(
            tam
        )

        if not sembol:
            continue

        sonuc.append({
            "sembol": sembol,
            "ham_metin": tam
        })

    return sonuc


def durum_oku():
    try:
        if DURUM_DOSYA.exists():
            veri = json.loads(
                DURUM_DOSYA.read_text(
                    encoding="utf-8"
                )
            )
            return set(veri)

    except Exception:
        pass

    return set()


def durum_yaz(ids):
    DURUM_DOSYA.write_text(
        json.dumps(
            sorted(list(ids)),
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def kayit_id(kayit):
    raw = (
        str(kayit.get("sembol", ""))
        + "|"
        + str(kayit.get("ham_metin", ""))
    ).encode(
        "utf-8",
        errors="ignore"
    )

    return hashlib.sha1(
        raw
    ).hexdigest()


def sadece_yeni_bildirimler(
    bildirimler
):
    mevcut_ids = {
        kayit_id(x)
        for x in bildirimler
    }

    # İlk açılış:
    # Geçmiş kayıtları alarm vermeden hafızaya al.
    if not DURUM_DOSYA.exists():

        durum_yaz(
            mevcut_ids
        )

        print(
            "ILK KAP SENKRONU | "
            f"{len(mevcut_ids)} mevcut kayit hafizaya alindi"
        )

        return []

    gorulen = durum_oku()

    yeniler = [
        x
        for x in bildirimler
        if kayit_id(x) not in gorulen
    ]

    gorulen.update(
        mevcut_ids
    )

    durum_yaz(
        gorulen
    )

    return yeniler


def kap_bildirim_isle(kayit):
    sembol = kayit.get(
        "sembol"
    )

    metin = kayit.get(
        "ham_metin",
        ""
    )

    sonuc = haber_zeka.kap_haber_isle(
        sembol=sembol,
        baslik=metin[:180],
        metin=metin,
        kaynak="KAP",
        fiyat_verisi=None
    )

    analiz = sonuc.get(
        "analiz",
        {}
    )

    alarm = sonuc.get(
        "alarm",
        {}
    )

    print(
        f"{sembol} | "
        f"{analiz.get('etki_sinifi', 'NOTR')} | "
        f"{analiz.get('etki_puani', 0):+.1f}/10"
    )

    if alarm.get("alarm"):
        print()
        print(
            alarm.get(
                "mesaj",
                ""
            )
        )
        print()

        web_alarm_kaydet(
            analiz,
            alarm
        )


def kap_kontrol():
    html = kap_sayfa_oku()

    bildirimler = kap_bildirimleri_ayir(
        html
    )

    yeniler = sadece_yeni_bildirimler(
        bildirimler
    )

    print(
        "KAP KONTROL | "
        f"GECERLI HISSE KAYDI: {len(bildirimler)} | "
        f"YENI: {len(yeniler)}"
    )

    for kayit in yeniler[:30]:
        kap_bildirim_isle(
            kayit
        )

    return len(yeniler)


def kap_surekli_izle(
    bekleme_saniye=60
):
    print(
        "KAP CANLI IZLEME BASLADI | "
        f"{bekleme_saniye} saniyede bir kontrol"
    )

    while True:

        try:
            kap_kontrol()

        except KeyboardInterrupt:
            print(
                "\nKAP IZLEME DURDURULDU"
            )
            break

        except Exception as e:
            print(
                "KAP IZLEME HATASI:",
                e
            )

        time.sleep(
            bekleme_saniye
        )



WEB_ALARM_DOSYA = Path(
    "webapp/data/kap_alarmlar.json"
)


def web_alarm_kaydet(analiz, alarm):
    if not alarm.get("alarm"):
        return False

    WEB_ALARM_DOSYA.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        if WEB_ALARM_DOSYA.exists():
            veri = json.loads(
                WEB_ALARM_DOSYA.read_text(
                    encoding="utf-8"
                )
            )
        else:
            veri = {
                "guncelleme": None,
                "alarmlar": []
            }

    except Exception:
        veri = {
            "guncelleme": None,
            "alarmlar": []
        }

    kayit = {
        "id": hashlib.sha1(
            (
                str(analiz.get("sembol", ""))
                + "|"
                + str(analiz.get("baslik", ""))
            ).encode(
                "utf-8",
                errors="ignore"
            )
        ).hexdigest()[:16],

        "tarih": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "sembol": analiz.get(
            "sembol",
            "-"
        ),

        "baslik": analiz.get(
            "baslik",
            ""
        ),

        "etki_puani": analiz.get(
            "etki_puani",
            0
        ),

        "etki_sinifi": analiz.get(
            "etki_sinifi",
            "NOTR"
        ),

        "guven": analiz.get(
            "guven",
            0
        ),

        "onem": analiz.get(
            "onem",
            0
        ),

        "fiyatlandi_riski": analiz.get(
            "fiyatlandi_riski",
            "BILINMIYOR"
        ),

        "alarm_seviyesi": alarm.get(
            "seviye",
            "YOK"
        ),

        "mesaj": alarm.get(
            "mesaj",
            ""
        )
    }

    alarmlar = veri.get(
        "alarmlar",
        []
    )

    alarmlar = [
        x
        for x in alarmlar
        if x.get("id") != kayit["id"]
    ]

    alarmlar.insert(
        0,
        kayit
    )

    veri["alarmlar"] = alarmlar[:100]

    veri["guncelleme"] = time.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    WEB_ALARM_DOSYA.write_text(
        json.dumps(
            veri,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print(
        "WEB KAP ALARMI KAYDEDILDI:",
        kayit["sembol"],
        kayit["alarm_seviyesi"]
    )

    return True

if __name__ == "__main__":
    kap_surekli_izle(
        60
    )
