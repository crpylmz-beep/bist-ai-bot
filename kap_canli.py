from veri_yollari import public_file, runtime_file

import re
import time
import json
import hashlib
import requests
import borsapy as bp
from pathlib import Path

from bs4 import BeautifulSoup
import haber_zeka
import canli_motor
from kullanici_kayitlari import atomic_json


KAP_URL = (
    "https://www.kap.org.tr/tr/bildirim-sorgu-sonuc"
    "?cat=6&cmp=Y&slf=ALL&srcbar=Y"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

DURUM_DOSYA = runtime_file('kap_son_gorulen.json')


def bist_sembolleri_getir():
    from pay_evreni import symbols
    return set(symbols())


BIST_SEMBOLLER = None  # Provider discovery is lazy; imports remain offline.


def kap_sayfa_oku():
    r = requests.get(
        KAP_URL,
        headers=HEADERS,
        timeout=20
    )

    r.raise_for_status()
    return r.text


def sembol_bul(text):
    global BIST_SEMBOLLER
    if BIST_SEMBOLLER is None:
        BIST_SEMBOLLER = bist_sembolleri_getir()
        if not BIST_SEMBOLLER:
            BIST_SEMBOLLER = None
            raise RuntimeError("KAP sembol listesi alinamadi")
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

        link=tr.find('a',href=True)
        from urllib.parse import urljoin
        from sirket_site_icerik import published_time
        sonuc.append({
            "sembol": sembol,
            "ham_metin": tam,
            "baslik": hucreler[-1],
            "url": urljoin(KAP_URL,link['href']) if link else '',
            "published_at": next((published_time(v) for v in hucreler if published_time(v)),None)
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
    atomic_json(DURUM_DOSYA, sorted(list(ids)))


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
    bildirimler, kaydet=True
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

    if kaydet:
        durum_yaz(gorulen)

    return yeniler


def kap_bildirim_isle(kayit):
    from haber_tekillestirme import CanonicalNews
    from kullanici_kayitlari import now
    text = kayit.get('ham_metin', '')
    event = {'sembol':kayit['sembol'], 'kaynak':'KAP',
             'baslik':kayit.get('baslik') or text[:180], 'metin':text,
             'url':kayit.get('url',''), 'published_at':kayit.get('published_at'),
             'discovered_at':now()}
    return CanonicalNews().process(event, enqueue=canli_motor.oncelikli_hisse_guncelle,
                                   alarm_writer=web_alarm_kaydet)


def kap_kontrol():
    html = kap_sayfa_oku()

    bildirimler = kap_bildirimleri_ayir(
        html
    )

    yeniler = sadece_yeni_bildirimler(
        bildirimler, kaydet=False
    )

    print(
        "KAP KONTROL | "
        f"GECERLI HISSE KAYDI: {len(bildirimler)} | "
        f"YENI: {len(yeniler)}"
    )

    gorulen = durum_oku()
    tamamlanan = 0
    hata = None
    for kayit in yeniler[:30]:
        try:
            kap_bildirim_isle(kayit)
            gorulen.add(kayit_id(kayit))
            durum_yaz(gorulen)
            tamamlanan += 1
        except Exception as error:
            from gorev_hatalari import describe,strongest
            hata = strongest([hata,describe(error)]) if hata else describe(error)
    if hata is not None:
        from gorev_hatalari import TaskIssue
        raise TaskIssue(hata,tamamlanan)
    return tamamlanan


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



WEB_ALARM_DOSYA = public_file('kap_alarmlar.json')


def web_alarm_kaydet(analiz, alarm, output_path=None):
    if not alarm.get("alarm"):
        return False

    output_path = Path(output_path) if output_path is not None else WEB_ALARM_DOSYA
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    try:
        if output_path.exists():
            veri = json.loads(
                output_path.read_text(
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
        "id": analiz.get("canonical_id") or hashlib.sha1(
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

    atomic_json(output_path, veri)

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
